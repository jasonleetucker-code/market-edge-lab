"""EXP-002 measurement: the label-free pre-freeze noise gate and the cross-book markout endpoint.

docs/research/RESEARCH_UNBLOCKING_DECISIONS.md A.A-A.C, A.G. Offline, fixture-based: SYNTHETIC stores only.
The gate must never load a T-60m book (a label); the markout runs only in a logged results path.
"""

from __future__ import annotations

import io
import json
import math
import random
import shutil
import socket
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab import research_evidence as rev
from edge_lab import sports_evidence as se
from edge_lab.dashboard import sports_fixtures as sf
from edge_lab.odds_schedule import iso_z
from edge_lab.storage import SnapshotStore

UTC = timezone.utc
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture(autouse=True)
def fixture_clock(monkeypatch):
    monkeypatch.setattr(se, "_clock", lambda: datetime(2026, 11, 1, tzinfo=UTC))


# ================================================================== pure statistics


def test_the_cross_book_statistic_takes_each_sign_from_one_book_and_the_markout_from_the_other():
    # c above H6 and c' above A6: both halves long; markouts are the OTHER book's moves.
    assert se.cross_book_markout(0.55, 0.55, 0.51, 0.52, 0.60, 0.54) == pytest.approx(0.5 * ((0.54 - 0.52) + (0.60 - 0.51)))
    # c below H6: the first half turns short.
    assert se.cross_book_markout(0.45, 0.55, 0.51, 0.52, 0.60, 0.54) == pytest.approx(0.5 * (-(0.54 - 0.52) + (0.60 - 0.51)))
    assert se.cross_book_markout(0.51, 0.52, 0.51, 0.52, 0.9, 0.9) == 0  # no gap, no position
    assert se.kalshi_only_placebo(0.50, 0.50, 0.51, 0.52, 0.60, 0.54) == pytest.approx(
        0.5 * (-(0.54 - 0.52) - (0.60 - 0.51)))


def _simulate(n: int, *, mirror: bool, informative: bool = False, seed: int = 7, noise: float = 0.005):
    rng = random.Random(seed)
    ys, pls = [], []
    for _ in range(n):
        l24 = rng.uniform(0.3, 0.7)
        l6 = l24 + rng.gauss(0, 0.03)
        l1 = l6 + rng.gauss(0, 0.02)
        c = (l1 if informative else l6) + rng.gauss(0, 0.01)

        def books(latent):
            e = rng.gauss(0, noise)
            f = e if mirror else rng.gauss(0, noise)
            return latent + e, latent + f  # H and A (home units)
        h24, a24 = books(l24)
        h6, a6 = books(l6)
        h1, a1 = books(l1)
        ys.append(se.cross_book_markout(c, c, h6, a6, h1, a1))
        pls.append(se.kalshi_only_placebo(h24, a24, h6, a6, h1, a1))
    mean = sum(ys) / n
    se_mean = math.sqrt(sum((y - mean) ** 2 for y in ys) / (n - 1) / n)
    return mean, se_mean, sum(pls) / n


def test_the_endpoint_is_centred_under_the_zero_information_null():
    for seed in (1, 2):
        mean, se_mean, placebo = _simulate(20_000, mirror=False, seed=seed)
        assert abs(mean) < 4 * se_mean
        assert abs(placebo) < 4 * se_mean * 1.5


def test_mirror_quoting_brings_the_bias_back():
    mean, se_mean, placebo = _simulate(20_000, mirror=True, seed=3)
    assert mean > 8 * se_mean  # the v1 same-book bias returns when the books mirror each other
    assert placebo > 0


def test_the_endpoint_detects_real_information():
    mean, se_mean, _ = _simulate(5_000, mirror=False, informative=True, seed=4)
    assert mean > 20 * se_mean


def _obs(*, n_weeks=8, per_week=25, rho=0.0, noise=0.005, gap_sd=0.03, mirror=False, repeat_zero=False, seed=11):
    rng = random.Random(seed)
    disp, rh, ra, gaps = [], [], [], []
    for w in range(n_weeks):
        week = f"nfl-week-of-2026-10-{w + 1:02d}"
        for _ in range(per_week):
            e = rng.gauss(0, noise)
            f = rho * e + math.sqrt(1 - rho * rho) * rng.gauss(0, noise)
            disp.append((week, 0.0 if mirror else e - f))
            rh.append((week, 0.0 if repeat_zero else rng.gauss(0, noise) - rng.gauss(0, noise)))
            ra.append((week, 0.0 if repeat_zero else rng.gauss(0, noise) - rng.gauss(0, noise)))
            gaps.append((week, rng.gauss(0, gap_sd)))
    return se.GateObservations(tuple(disp), tuple(rh), tuple(ra), tuple(gaps), tuple([300] * len(rh)), {}, ())


def test_the_gate_passes_independent_books_and_derives_rho_max():
    gate = se.noise_gate(_obs(), min_effect=0.0025, resamples=400)
    est = gate["estimates"]
    assert abs(est["rho_hat"]) < 0.3 and est["rho_upper_90"] < gate["verdict_for_min_effect"]["rho_max"]
    assert gate["verdict"] == se.PASS
    expected_b = (est["sigma2_home"] + est["sigma2_away"]) / 2 * math.sqrt(2 / math.pi) / est["gap_sd"]
    assert est["b_hat"] == pytest.approx(expected_b)
    assert gate["verdict_for_min_effect"]["rho_max"] == pytest.approx(min(1.0, 0.25 * 0.0025 / expected_b))


def test_the_gate_fails_correlated_books_and_mirror_quoting():
    correlated = se.noise_gate(_obs(rho=0.8, gap_sd=0.01), min_effect=0.0025, resamples=400)
    assert correlated["estimates"]["rho_hat"] > 0.6 and correlated["verdict"] == se.FAIL
    mirror = se.noise_gate(_obs(mirror=True), resamples=400)
    assert mirror["verdict"] == se.FAIL and mirror["estimates"]["mirror_quoting"]
    assert all(row["verdict"] == se.FAIL and "MIRROR" in row["why"] for row in mirror["by_candidate_min_effect"])


def test_the_gate_never_invents_min_effect_and_says_when_data_are_insufficient():
    undecided = se.noise_gate(_obs(), resamples=200)
    assert undecided["min_effect"] is None and undecided["min_effect_state"].startswith("UNKNOWN")
    assert undecided["verdict"] == "BY_MIN_EFFECT" and undecided["verdict_for_min_effect"] is None
    assert [r["min_effect"] for r in undecided["by_candidate_min_effect"]] == list(se.CANDIDATE_MIN_EFFECTS)
    thin = se.noise_gate(_obs(n_weeks=1, per_week=5), min_effect=0.005, resamples=200)
    assert thin["verdict"] == se.INSUFFICIENT and thin["insufficient"]
    frozen_quotes = se.noise_gate(_obs(repeat_zero=True), min_effect=0.005, resamples=200)
    assert frozen_quotes["verdict"] == se.INSUFFICIENT
    assert any("REPEAT_NOISE_ZERO" in x for x in frozen_quotes["insufficient"])


# ================================================================== SYNTHETIC store


TEAMS = list(se.NFL_TEAMS)
KICKOFF = datetime(2026, 9, 27, 17, 0, tzinfo=UTC)


def _games(n_weeks: int = 2, per_week: int = 6) -> list[sf.Game]:
    return [sf.Game(f"fxm{w}{i:02d}", TEAMS[2 * i], TEAMS[2 * i + 1], KICKOFF + timedelta(days=7 * w),
                    Decimal("0.55")) for w in range(n_weeks) for i in range(per_week)]


def _ask(mid: float) -> Decimal:
    return (Decimal(str(mid)) + Decimal("0.01")).quantize(Decimal("0.01"))  # sf._book: mid = ask - 0.01


def build_store(tmp_path: Path, *, mirror: bool = False, seed: int = 5) -> tuple[Path, datetime, dict]:
    """Every due horizon of 12 games over 2 weeks gets a book per team 60 s after its odds capture, and a repeat
    5 min later. T-60m gets a later second book with a very different price, so the FIRST one is checkable."""
    games = _games()
    now = max(g.commence for g in games) + timedelta(hours=1)
    store = SnapshotStore(tmp_path / "exp002.sqlite3")
    sf.write_pairing_fixture(store, games=games, now=now, books=False)
    rows = se.build_report(SnapshotStore.open_readonly(store.path), as_of=now)["rows"]
    rng = random.Random(seed)
    sids = {"T-24h": set(), "T-6h": set(), "T-60m": set(), "t60_first": {}, "t60_second": set()}
    store.start_run("SYNTHETIC-exp002-books")
    for r in rows:
        received = r["odds"].get("received_utc")
        tickers = (r.get("kalshi") or {}).get("tickers") or {}
        if not received or not tickers:
            continue
        at = datetime.fromisoformat(received.replace("Z", "+00:00"))
        home, away = r["home_team"], r["away_team"]
        latent = {"T-24h": 0.50, "T-6h": 0.51, "T-60m": 0.54}[r["horizon"]]
        noise_h = rng.choice((-0.01, 0.0, 0.01))
        noise_a = noise_h if mirror else rng.choice((-0.01, 0.0, 0.01))
        mids = {home: latent + noise_h, away: 1 - (latent + noise_a)}
        for team, ticker in sorted(tickers.items()):
            for offset, shift in ((60, 0.0), (300, 0.0 if r["horizon"] != "T-60m" else (0.05 if team == home else -0.05))):
                mid = mids[team] + shift + (rng.choice((-0.01, 0.01)) if offset == 300 and r["horizon"] != "T-60m" else 0)
                sid = store.save_snapshot(run_id="SYNTHETIC-exp002-books", source=se.KALSHI, kind="orderbook",
                                          entity_id=ticker, url=f"{sf.KALSHI_API}/markets/{ticker}/orderbook?depth=100",
                                          payload=sf._book(_ask(round(mid, 2))),
                                          fetched_at_utc=iso_z(at + timedelta(seconds=offset)),
                                          source_id="kalshi_public")
                sids[r["horizon"]].add(sid)
                if r["horizon"] == "T-60m":
                    if offset == 60:
                        sids["t60_first"][(r["event_id"], team)] = (sid, round(mids[team], 2))
                    else:
                        sids["t60_second"].add(sid)
    store.finish_run("SYNTHETIC-exp002-books", status="succeeded")
    return store.path, now, sids


def test_the_gate_never_loads_a_t60m_book(tmp_path, monkeypatch):
    path, now, sids = build_store(tmp_path)
    loaded: list[int] = []
    original = se._Payloads.payload

    def spy(self, sid):
        loaded.append(sid)
        return original(self, sid)

    monkeypatch.setattr(se._Payloads, "payload", spy)
    out = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now)
    books_loaded = set(loaded) & (sids["T-24h"] | sids["T-6h"] | sids["T-60m"])
    assert books_loaded and not books_loaded & sids["T-60m"]  # label books are never loaded
    assert books_loaded <= sids["T-24h"] | sids["T-6h"]
    assert set(out["gate_books_read"]) <= sids["T-24h"] | sids["T-6h"]  # the gate's reader: repeats only
    assert out["markout"]["state"] == "HIDDEN" and out["labels"] == "HIDDEN"
    gate = out["gate"]
    assert gate["label_free"] and gate["counts"]["dispersion_pairs"] == 24  # 12 games x (T-24h, T-6h)
    assert gate["counts"]["repeat_home"] == gate["counts"]["repeat_away"] == 24
    assert gate["repeat_gap_seconds"]["median"] == 240 and gate["counts"]["weeks"] == 2
    assert gate["min_effect_state"].startswith("UNKNOWN")


def test_mirror_quoted_books_fail_the_gate_on_a_store(tmp_path):
    path, now, _ = build_store(tmp_path, mirror=True)
    gate = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now, min_effect=0.005)["gate"]
    assert gate["estimates"]["mirror_quoting"] and gate["verdict"] == se.FAIL


def test_the_markout_uses_the_first_t60m_book_and_counts_every_game(tmp_path):
    path, now, sids = build_store(tmp_path)
    out = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now, results=True)
    m = out["markout"]
    assert out["labels"].startswith("INCLUDED") and m["counts"]["evaluated"] == 12 == len(m["games"])
    assert m["counts"]["with_placebo"] == 12 and m["summary"]["weeks"] == 2
    second = sids["t60_second"]
    for g in m["games"]:
        assert g["t60_books"]["home"]["snapshot_id"] == sids["t60_first"][(g["event_id"], g["home_team"])][0]
        assert g["t60_books"]["home"]["snapshot_id"] not in second
        expected = 0.5 * (se._sign(g["consensus_value_home"] - g["H6"]) * (g["A1"] - g["A6"])
                          + se._sign(g["consensus_value_home_from_away"] - g["A6"]) * (g["H1"] - g["H6"]))
        assert g["y"] == pytest.approx(expected)
        assert g["consensus_basis"].startswith("UNADJUSTED")  # the tie bounds are not declared
        assert set(g["t6_book_timing"].values()) == {se.BOOK_AT_OR_AFTER_ODDS}
    assert m["pilot_outputs"]["t6_pairing_yield"] == 1.0 and m["pilot_outputs"]["t60_book_yield"] == 1.0
    assert m["summary"]["state"].startswith("PILOT DESCRIPTIVE")
    assert m["t6_book_timing"][se.BOOK_AT_OR_AFTER_ODDS] == 24


def test_declared_tie_bounds_move_the_sign_reference_to_the_interval_midpoint(tmp_path):
    path, now, _ = build_store(tmp_path)
    policy = se.JoinPolicy(tie_probability_bound=Decimal("0.01"), postponement_probability_bound=Decimal("0.005"))
    m = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now, results=True, policy=policy)["markout"]
    assert m["games"] and all(g["consensus_basis"] == "TIE_ADJUSTED_MIDPOINT" for g in m["games"])


def _registry_copy(tmp_path: Path) -> tuple[Path, Path]:
    src = next((REPO / "experiments").glob("EXP-002-*"))
    root = tmp_path / "experiments"
    shutil.copytree(src, root / src.name)
    return root, root / src.name / "evidence_use.jsonl"


def test_cli_hides_labels_unless_the_view_is_logged_first(tmp_path):
    path, now, _ = build_store(tmp_path)
    root, own = _registry_copy(tmp_path)
    base = ["exp002", "--db", str(path), "--as-of", iso_z(now), "--experiments", str(root)]
    before = len(rev.read_log(own).uses)
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert se.main(base) == 0
    plain = json.loads(buf.getvalue())
    assert plain["markout"]["state"] == "HIDDEN" and "games" not in plain["markout"]
    assert len(rev.read_log(own).uses) == before  # the label-free run logs nothing
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert se.main(base + ["--with-results"]) == 2  # refused: no log, actor or code version
    assert json.loads(buf.getvalue())["state"] == "REFUSED" and '"games"' not in buf.getvalue()
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert se.main(base + ["--with-results", "--min-effect", "0.005", "--evidence-log", str(own),
                               "--actor", "test", "--code-version", "abc123"]) == 0
    shown = json.loads(buf.getvalue())
    assert shown["evidence_use"] == "APPENDED" and shown["markout"]["counts"]["evaluated"] == 12
    assert shown["gate"]["min_effect"] == 0.005 and shown["gate"]["verdict_for_min_effect"] is not None
    uses = rev.read_log(own).uses
    assert len(uses) == before + 1 and uses[-1].action is rev.Action.LABEL_RESULT_INSPECTION
    assert uses[-1].dataset_id == "sports_evidence:exp002_markout" and uses[-1].dataset_sha256 == shown["output_sha256"]
    assert "exp002 --with-results" in uses[-1].tool


def test_the_measurement_is_deterministic(tmp_path):
    path, now, _ = build_store(tmp_path)
    a = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now, results=True)
    b = se.measure_exp002(SnapshotStore.open_readonly(path), as_of=now, results=True)
    assert a == b and a["output_sha256"] == b["output_sha256"]
