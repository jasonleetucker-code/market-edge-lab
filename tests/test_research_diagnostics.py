"""Track B harness: evidence stamps, calibration by bucket, governance guard and CLI (#184, ADR 0050)."""

import json
import math
from decimal import Decimal as D

import pytest

from edge_lab import research_diagnostics as rd
from edge_lab.research_diagnostics import EvidenceClass, PredictionRow, calibration_report

PRICE_EDGES = [D("0"), D("0.2"), D("0.4"), D("0.6"), D("0.8"), D("1")]
TTE_EDGES = [D(0), D(600), D(3600)]
EVENT = "eu-" + "0" * 32


def row(rid, market, cluster, price, outcome, *, size=D(1), tte=D(1000), side="YES", category="nba",
        scope="sports:nba:moneyline"):
    return PredictionRow(rid, market, cluster, scope, category, side, D(price),
                         None if tte is None else D(tte), None if outcome is None else D(outcome),
                         None if size is None else D(size), "TRADE_PRICE")


def report(rows, klass=EvidenceClass.SYNTHETIC, **kw):
    return calibration_report(rows, price_edges=PRICE_EDGES, tte_edges_seconds=TTE_EDGES, evidence_class=klass,
                              code_version="test", **kw)


BASE = [
    row("r1", "novig:m1", "g1", "0.30", 0, size=D(1)),
    row("r2", "novig:m1", "g1", "0.34", 0, size=D(3)),
    row("r3", "novig:m2", "g1", "0.30", 1, size=D(4)),
]


def _bucket(rep, price="[0.2,0.4)", tte="[600,3600)", side="YES"):
    return next(b for b in rep.buckets if (b.price_bucket, b.tte_bucket, b.side) == (price, tte, side))


# --------------------------------------------------------------------------- exactness


def test_market_and_trade_weighted_views_are_exact_and_separate():
    b = _bucket(report(BASE))
    mw, tw = b.market_weighted, b.trade_weighted
    # market-weighted: m1's two rows weigh 1/2 each, m2's row weighs 1
    assert (mw.weight_total, mw.mean_price, mw.realized_frequency, mw.deviation, mw.brier) == (
        D("2.000000000000"), D("0.310000000000"), D("0.500000000000"), D("0.190000000000"), D("0.296400000000"))
    # trade-weighted: sizes 1, 3, 4
    assert (tw.weight_total, tw.mean_price, tw.realized_frequency, tw.brier) == (
        D("8.000000000000"), D("0.315000000000"), D("0.500000000000"), D("0.299600000000"))
    expected_ll = -(0.5 * math.log(0.7) + 0.5 * math.log(0.66) + math.log(0.30)) / 2
    assert abs(float(mw.log_loss) - expected_ll) < 1e-12
    assert mw != tw


def test_decimal_results_are_deterministic_and_hashed():
    a, b = report(BASE), report(list(reversed(BASE)))
    assert a.buckets == b.buckets  # row order never changes a statistic
    assert report(BASE).report_sha256 == a.report_sha256 and len(a.report_sha256) == 64
    assert isinstance(a.buckets[0].market_weighted.brier, D)


# --------------------------------------------------------------------------- clusters, not rows


def test_cluster_count_is_not_the_row_count():
    b = _bucket(report(BASE))
    assert (b.rows, b.markets, b.clusters) == (3, 2, 1)
    assert b.deviation_band is None and "fewer than two" in b.band_reason


def test_band_resamples_clusters():
    rows = BASE + [row("r4", "novig:m3", "g2", "0.30", 0), row("r5", "novig:m4", "g3", "0.25", 1)]
    b = _bucket(report(rows))
    assert b.clusters == 3 and b.rows == 5
    assert b.deviation_band is not None and b.deviation_band.clusters == 3
    assert b.deviation_band.lower <= b.deviation_band.mean <= b.deviation_band.upper


def test_a_market_in_two_clusters_is_refused():
    with pytest.raises(ValueError, match="two clusters"):
        report(BASE + [row("r9", "novig:m1", "g2", "0.30", 0)])


# --------------------------------------------------------------------------- unknowns propagate


def test_unknown_outcomes_are_counted_and_never_scored_as_zero():
    with_unknown = BASE + [row("r4", "novig:m5", "g9", "0.38", None)]
    b = _bucket(report(with_unknown))
    assert b.unknown_outcome_rows == 1 and b.rows == 3
    assert b.market_weighted == _bucket(report(BASE)).market_weighted
    rep = report(with_unknown)
    assert (rep.rows_total, rep.rows_known_outcome, rep.rows_unknown_outcome) == (4, 3, 1)


def test_unknown_trade_size_blocks_only_the_trade_weighted_view():
    rows = BASE[:2] + [row("r3", "novig:m2", "g1", "0.30", 1, size=None)]
    b = _bucket(report(rows))
    assert b.trade_weighted is None and b.trade_weighted_reason.startswith("TRADE_SIZE_UNKNOWN")
    assert b.market_weighted is not None


def test_unknown_time_to_close_gets_its_own_bucket():
    rep = report([row("r1", "novig:m1", "g1", "0.30", 0, tte=None)])
    assert rep.buckets[0].tte_bucket == "UNKNOWN"


def test_bucket_boundaries_are_half_open_with_a_closed_top():
    rep = report([row("a", "novig:a", "c1", "0.2", 0, tte=D(600)), row("b", "novig:b", "c2", "0.9999", 1,
                                                                      tte=D(999999))])
    keys = {(b.price_bucket, b.tte_bucket) for b in rep.buckets}
    assert keys == {("[0.2,0.4)", "[600,3600)"), ("[0.8,1]", "[3600,inf)")}


# --------------------------------------------------------------------------- favorite / longshot


def test_favorite_longshot_view_pools_buckets_within_a_side():
    rows = [row(f"l{i}", f"novig:l{i}", f"c{i}", "0.10", 0, tte=D(100 * i)) for i in range(1, 6)]
    rows += [row(f"f{i}", f"novig:f{i}", f"d{i}", "0.90", 1) for i in range(1, 4)]
    rep = report(rows)
    fl = {(r.side, r.price_bucket): r for r in rep.favorite_longshot}
    longshot, favorite = fl[("YES", "[0,0.2)")], fl[("YES", "[0.8,1]")]
    assert longshot.rows == 5 and longshot.clusters == 5
    assert longshot.market_weighted.deviation == D("-0.100000000000")  # longshots paid less often than priced
    assert favorite.market_weighted.deviation == D("0.100000000000")
    assert [r.price_bucket for r in rep.favorite_longshot] == ["[0,0.2)", "[0.8,1]"]


# --------------------------------------------------------------------------- stamps and governance


def test_synthetic_label_cannot_be_missed():
    stamp = report(BASE).stamp
    assert stamp.evidence_class == "SYNTHETIC" and stamp.edge_claim == "NONE"
    assert "NOT AN EDGE" in stamp.label and stamp.label.startswith("SYNTHETIC")
    assert stamp.code_version == "test" and len(stamp.input_sha256) == 64
    assert report(BASE[:2]).stamp.input_sha256 != stamp.input_sha256


def test_governed_classes_need_experiment_and_logged_event():
    for klass in (EvidenceClass.RETROSPECTIVE_EXPLORATORY, EvidenceClass.PROSPECTIVE):
        with pytest.raises(ValueError, match="experiment id"):
            report(BASE, klass)
        with pytest.raises(ValueError, match="evidence-use event"):
            report(BASE, klass, experiment_id="EXP-010")
        ok = report(BASE, klass, experiment_id="EXP-010", evidence_use_event_id=EVENT)
        assert ok.stamp.label.startswith(klass.value.replace("_", " "))


@pytest.mark.parametrize("market,scope", [
    ("kalshi:KXNFLGAME-26OCT11ATLGB-GB", "sports:kalshi:other"),  # caught by series
    ("kalshi:KXNHLGAME-26OCT11BOSNYR-BOS", "sports:nhl:moneyline"),
    ("kalshi:KXHIGHNY-26OCT11-T70", "weather:nyc"),
    ("novig:abc", "sports:nfl:moneyline"),  # caught by scope
    ("novig:abc", "SPORTS:NFL:MONEYLINE:week5"),
])
def test_protected_label_scopes_are_refused_for_governed_runs(market, scope):
    rows = [row("x", market, "c", "0.5", 1, scope=scope)]
    with pytest.raises(ValueError, match="protected label scope"):
        report(rows, EvidenceClass.RETROSPECTIVE_EXPLORATORY, experiment_id="EXP-010", evidence_use_event_id=EVENT)
    assert report(rows).stamp.evidence_class == "SYNTHETIC"  # a code test may use the shape


def test_invalid_rows_raise():
    for bad in (row("x", "novig:m", "c", "1", 1), row("x", "novig:m", "c", "0.5", 2),
                row("x", "novig:m", "c", "0.5", 1, size=D(0)), row("x", "novig:m", "c", "0.5", 1, tte=D(-1))):
        with pytest.raises(ValueError):
            report([bad])


# --------------------------------------------------------------------------- CLI


def _write_protocol(root, inputs, scopes, fields):
    from edge_lab.research_evidence import init_log

    d = root / "EXP-010-track-b-test"
    d.mkdir(parents=True)
    (d / "experiment.toml").write_text('id = "EXP-010"\n', encoding="utf-8")
    (d / "protocol.toml").write_text(
        "[data_roles]\nprohibited_inputs = " + json.dumps(inputs) + "\nprohibited_label_scopes = "
        + json.dumps(scopes) + "\nprohibited_fields = " + json.dumps(fields) + "\n", encoding="utf-8")
    init_log(d / "evidence_use.jsonl", experiment_id="EXP-010", started_at_utc="2026-10-08T00:00:00Z")
    return d


def test_guard_requires_the_track_b_prohibitions_and_a_logged_event(tmp_path):
    _write_protocol(tmp_path, ["exp001:"], ["kalshi:kxhighny"], ["result"])
    problems = rd.protocol_guard_problems("EXP-010", EVENT, root=tmp_path)
    text = "\n".join(problems)
    assert "prohibited_inputs" in text and "prohibited_label_scopes" in text and "prohibited_fields" in text
    assert "not in EXP-010's evidence-use log" in text


def test_guard_passes_with_full_prohibitions_and_a_logged_event(tmp_path):
    from edge_lab.research_evidence import (
        Action, DatasetRole, EvidenceUse, InformationWindow, record_use,
    )

    d = _write_protocol(tmp_path, list(rd.TRACK_B_PROHIBITED_INPUTS),
                        [s.lower() for s in rd.TRACK_B_PROHIBITED_LABEL_SCOPES], list(rd.TRACK_B_PROHIBITED_FIELDS))
    use = EvidenceUse("EXP-010", "TB-CAL", "fixture:rows", "v1", "0" * 64, DatasetRole.DEVELOPMENT,
                      InformationWindow("sports:nba:moneyline", "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"),
                      "test", "pytest", "2026-10-08T00:00:00Z", Action.FEATURE_INSPECTION, "test", None, None,
                      True, False, False, False)
    record_use(d / "evidence_use.jsonl", use)
    assert rd.protocol_guard_problems("EXP-010", use.event_id, root=tmp_path) == []


def test_cli_runs_on_a_fixture_file_and_refuses_ungoverned_retrospective_runs(tmp_path, capsys):
    rows = tmp_path / "rows.jsonl"
    rows.write_text("\n".join(json.dumps({"row_id": r.row_id, "market_id": r.market_id, "cluster_id": r.cluster_id,
                                          "scope": r.scope, "category": r.category, "side": r.side,
                                          "price": str(r.price), "time_to_close_seconds": "1000",
                                          "outcome": str(r.outcome), "trade_size": str(r.trade_size)})
                              for r in BASE) + "\n", encoding="utf-8")
    args = ["calibration", "--rows", str(rows), "--price-edges", "0,0.2,0.4,0.6,0.8,1", "--tte-edges", "0,600,3600",
            "--code-version", "test"]
    assert rd.main(args + ["--evidence-class", "FIXTURE"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["stamp"]["evidence_class"] == "FIXTURE" and out["rows_total"] == 3
    assert rd.main(args + ["--evidence-class", "RETROSPECTIVE_EXPLORATORY"]) == 2
    assert rd.main(args + ["--evidence-class", "RETROSPECTIVE_EXPLORATORY", "--experiment", "EXP-010",
                           "--evidence-use-event", EVENT, "--experiments-root", str(tmp_path)]) == 2
    assert "refused" in capsys.readouterr().err
