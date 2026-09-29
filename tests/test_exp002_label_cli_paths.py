"""EXP-002 label CLI paths: the remaining display commands that could show EXP-002 labels.

1. `sports_evidence report`: a related Polymarket US capture at T-60m, or received after the T-6h decision cutoff,
   is a correlated proxy for the Kalshi T-60m label (EXP002_FREEZE_PROPOSAL.md §4). Its price is withheld from every
   row, the `--out` file and the summary, unless a logged --with-results run shows it (and records it).
2. `observe status --market kalshi:KXNFLGAME-...` (`price_observations.market_history`, `status`): NFL pairing books
   at T-60m or after the T-6h cutoff and settlement reads lose their prices, sizes, depth and free-text reasons.
   EXP-001 / KXHIGHNY and ADR 0030 rows are exactly unchanged.

SYNTHETIC fixtures only; no network, no production data.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import socket
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from edge_lab import cli
from edge_lab import price_observations as po
from edge_lab import research_evidence as rev
from edge_lab import sports_evidence as se
from edge_lab.dashboard import sports_fixtures as sf
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
    monkeypatch.setattr(po, "_now", lambda: datetime(2026, 11, 1, tzinfo=UTC))  # `observe status` now_utc


_ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_HEX_ID = re.compile(r"\b[0-9a-f]{8,}(?:-[0-9a-f]{4,})*\b")


def _scrub(text: str) -> str:
    """`text` with ISO timestamps and hex / uuid ids replaced before a figure's substring check: a recorded-at time
    (wall clock, microseconds) or a random id may contain a figure's digits without being one."""
    return _HEX_ID.sub("<id>", _ISO_TIME.sub("<time>", text))


def _run(fn, argv) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = fn(argv)
    return code, _scrub(buf.getvalue())


# ================================================================== 1. sports_evidence report: related-market proxies

PRE, T60, LATE = "0.9111", "0.9137", "0.9173"  # distinctive SYNTHETIC prices (nothing else in the report is near 0.91)


def _pm_store(tmp_path: Path) -> tuple[Path, datetime]:
    """The pairing fixture plus three Polymarket US captures of a market related to fxsyn002 (kickoff 17:00Z):
    a T-6h capture before the decision cutoff (keeps its price), a T-60m capture and a T-6h capture received after
    the cutoff (both label proxies)."""
    path, now = sf.fixture_store(tmp_path)
    store = SnapshotStore(path)
    store.start_run("SYNTHETIC-pm")
    store.record_pm_sports_scan({
        "scan_id": "SYNTHETIC-scan", "run_id": "SYNTHETIC-pm", "league": "nfl", "endpoint": "events",
        "started_at_utc": "2026-09-26T10:00:00Z", "completed_at_utc": "2026-09-26T10:00:05Z",
        "coverage_state": "PARTIAL", "filter_complete": 1, "pages_ok": 1, "requests": 1, "events": 1, "markets": 1,
        "coverage_detail": "SYNTHETIC", "page_snapshot_ids_json": "[]", "catalog_json": "[]", "anomalies_json": "[]",
        "parser_version": "x", "policy_version": "x"})
    for tid, slug, offset, prio, target, due, deadline in (
            ("SYNTHETIC-pm-6", "synthetic-kc-mia", "T-6h", 2, "2026-09-27T11:00:00Z", "2026-09-27T10:53:00Z",
             "2026-09-27T11:30:00Z"),
            ("SYNTHETIC-pm-6b", "synthetic-kc-mia-alt", "T-6h", 2, "2026-09-27T11:00:00Z", "2026-09-27T10:53:00Z",
             "2026-09-27T11:30:00Z"),
            ("SYNTHETIC-pm-1", "synthetic-kc-mia", "T-60m", 1, "2026-09-27T16:00:00Z", "2026-09-27T15:53:00Z",
             "2026-09-27T16:30:00Z")):
        store.plan_pm_sports_target({
            "target_id": tid, "league": "nfl", "market_slug": slug, "odds_event_id": "fxsyn002",
            "relationship": "RELATED_NOT_EQUIVALENT", "relationship_json": "{}", "offset_label": offset,
            "priority": prio, "game_start_utc": "2026-09-27T17:00:00Z", "target_utc": target, "effective_utc": target,
            "due_from_utc": due, "deadline_utc": deadline, "planned_at_utc": "2026-09-26T10:00:00Z",
            "scan_id": "SYNTHETIC-scan", "policy_version": "x", "detail_json": "{}"})
    for attempt, tid, received, ask in (("a-pre", "SYNTHETIC-pm-6", "2026-09-27T11:00:10Z", PRE),
                                        ("a-late", "SYNTHETIC-pm-6b", "2026-09-27T11:40:00Z", LATE),
                                        ("a-t60", "SYNTHETIC-pm-1", "2026-09-27T16:00:10Z", T60)):
        snap = store.save_snapshot(run_id="SYNTHETIC-pm", source="polymarket_us", kind="book",
                                   entity_id="synthetic-kc-mia", url="https://gateway.polymarket.us/SYNTHETIC",
                                   payload={"SYNTHETIC": attempt}, fetched_at_utc=received)
        store.record_pm_sports_observation({
            "run_id": "SYNTHETIC-pm", "attempt_id": attempt, "target_id": tid, "status": "CAPTURED",
            "received_at_utc": received, "snapshot_id": snap, "yes_ask": ask, "yes_ask_size": "12", "freshness": "fresh",
            "recorded_at_utc": received, "policy_version": "x"})
    store.finish_run("SYNTHETIC-pm", status="succeeded")
    return path, now


def test_the_report_withholds_related_market_label_proxies_everywhere(tmp_path):
    path, now = _pm_store(tmp_path)
    rep = se.build_report(SnapshotStore.open_readonly(path), as_of=now)
    text = _scrub(json.dumps(rep))
    assert T60 not in text and LATE not in text  # neither the T-60m nor the post-cutoff capture's price
    rows = {(r["event_id"], r["horizon"]): r for r in rep["rows"]}
    t60 = rows[("fxsyn002", "T-60m")]["related_not_equivalent"]
    assert len(t60) == 3  # every capture stays listed: availability, never a price
    hidden = [x for x in t60 if x["is_label_proxy"]]
    assert len(hidden) == 2 and all("yes_ask" not in x and x["label_proxy"].startswith("HIDDEN") for x in hidden)
    pre = next(x for x in t60 if not x["is_label_proxy"])
    assert pre["yes_ask"] == PRE and pre["offset_label"] == "T-6h" and "label_proxy" not in pre
    assert rows[("fxsyn002", "T-6h")]["related_not_equivalent"][0]["yes_ask"] == PRE  # pre-decision keeps its price
    # the CLI: plain JSON, --out file and --summary
    code, out = _run(se.main, ["report", "--db", str(path), "--as-of", now.isoformat()])
    assert code == 0 and T60 not in out and LATE not in out and PRE in out
    code, out = _run(se.main, ["report", "--db", str(path), "--as-of", now.isoformat(), "--out",
                               str(tmp_path / "rep.json")])
    written = _scrub((tmp_path / "rep.json").read_text(encoding="utf-8"))
    assert code == 0 and T60 not in written and LATE not in written and PRE in written
    code, out = _run(se.main, ["report", "--db", str(path), "--as-of", now.isoformat(), "--summary"])
    assert code == 0 and T60 not in out and LATE not in out


def test_a_related_entry_with_an_unknown_horizon_or_state_fails_closed():
    entries = [{"yes_ask": "0.5", "is_label_proxy": None}, {"yes_ask": "0.5"}, {"yes_ask": "0.5", "is_label_proxy": False}]
    out = se._hide_related_proxies(entries)
    assert "yes_ask" not in out[0] and "yes_ask" not in out[1] and out[2]["yes_ask"] == "0.5"
    assert se.pms.is_label_proxy(None, "2026-09-27T17:00:00Z", "2026-09-27T10:00:00Z")  # unknown horizon


def _registry_copy(tmp_path: Path) -> tuple[Path, Path]:
    src = next((REPO / "experiments").glob("EXP-002-*"))
    root = tmp_path / "experiments"
    shutil.copytree(src, root / src.name)
    return root, root / src.name / "evidence_use.jsonl"


def test_only_the_logged_results_run_shows_related_proxies_and_records_them(tmp_path):
    path, now = _pm_store(tmp_path)
    root, own = _registry_copy(tmp_path)
    before = len(rev.read_log(own).uses)
    base = ["report", "--db", str(path), "--as-of", now.isoformat(), "--experiments", str(root)]
    code, out = _run(se.main, base + ["--with-results"])
    assert code == 2 and T60 not in out and LATE not in out  # refused without a log
    code, out = _run(se.main, base + ["--with-results", "--evidence-log", str(own), "--actor", "test",
                                      "--code-version", "abc123"])
    assert code == 0 and T60 in out and LATE in out
    use = rev.read_log(own).uses[-1]
    assert len(rev.read_log(own).uses) == before + 1 and use.action is rev.Action.LABEL_RESULT_INSPECTION
    assert "related-market (Polymarket US) label-proxy" in use.note
    assert use.window.start_utc <= "2026-09-27T17:00:00Z" <= use.window.end_utc  # fxsyn002 is in the window


def test_the_recorded_window_includes_a_game_shown_only_through_its_related_proxy(tmp_path):
    rows = [{"commence_utc": "2026-10-04T17:00:00Z", "outcome": {"x": {}}, "related_not_equivalent": []},
            {"commence_utc": "2026-10-11T17:00:00Z", "outcome": se.OUTCOMES_HIDDEN,
             "related_not_equivalent": [{"is_label_proxy": True, "yes_ask": "0.5"}]},
            {"commence_utc": "2026-10-18T17:00:00Z", "outcome": se.OUTCOMES_HIDDEN,
             "related_not_equivalent": [{"is_label_proxy": False, "yes_ask": "0.5"}]}]
    root, own = _registry_copy(tmp_path)
    protocol = se.protocol_status(root)
    se.record_results_view({"rows": rows, "protocol": protocol, "as_of_utc": "2026-11-01T00:00:00Z",
                            "output_sha256": "0" * 64}, log=own, actor="t", code_version="abc", experiments_root=root)
    window = rev.read_log(own).uses[-1].window
    assert (window.start_utc, window.end_utc) == ("2026-10-04T17:00:00Z", "2026-10-11T17:00:00Z")


# ================================================================== 2. observe status: Kalshi NFL books and settlements

KICKOFF = datetime(2026, 10, 4, 17, 0, tzinfo=UTC)
TICKER = "KXNFLGAME-26OCT04ARINYG-NYG"
MARKET = f"kalshi:{TICKER}"
LABEL_PRICES = ("0.6123", "0.6377", "0.6411", "0.6433", "0.6455")  # distinctive SYNTHETIC label figures


def _nfl_target(offset: str, at: datetime, *, deadline: timedelta = timedelta(minutes=29)) -> dict:
    t = po.custom_target(venue="kalshi", native_market_id=TICKER, at=at, native_event_id="KXNFLGAME-26OCT04ARINYG")
    t.update(origin=po.NFL_ORIGIN, deadline_utc=po._iso(at + deadline), detail={
        "nfl_role": po.NFL_ROLE_BOOK, "version": po.NFL_PLAN_VERSION, "odds_target_id": f"odds-{offset}",
        "odds_offset": offset, "commence_utc": po._iso(KICKOFF), "game_date": "2026-10-04"})
    return t


def _row(store, run, target, *, status, at=None, bid=None, ask=None, reason=None, side="YES"):
    snap = None
    if at is not None:
        snap = store.save_snapshot(run_id=run, source="kalshi", kind="orderbook", entity_id=target["native_market_id"],
                                   url="https://SYNTHETIC/orderbook", payload={"SYNTHETIC": target["target_id"]},
                                   fetched_at_utc=po._iso(at))
    extra = {}
    if status == "CAPTURED":
        extra = dict(bid=bid, ask=ask, ask_size="7", depth_json=json.dumps({"asks": [[ask, "7"]]}),
                     price_grid_json=json.dumps({"source": "SYNTHETIC", "ranges": []}))
    row = po._base_row(run, f"{run}-{target['target_id']}", target, status=status, reason=reason,
                       side=side if at is not None else None,
                       observed_at_utc=po._iso(at) if at is not None else None, snapshot_id=snap,
                       freshness="fresh" if at is not None else "unknown", **extra)
    store.record_price_observations([row])


def _obs_store(tmp_path: Path, *, nfl: bool = True) -> tuple[SnapshotStore, dict]:
    store = SnapshotStore(tmp_path / "obs.sqlite3")
    run = "SYNTHETIC-obs"
    store.start_run(run)
    ids = {}
    # EXP-001 / KXHIGHNY: a manual custom target and an ADR 0030 post-decision target, both captured
    hi = po.custom_target(venue="kalshi", native_market_id="KXHIGHNY-26OCT04-B67.5", at=KICKOFF - timedelta(hours=30))
    adr = {**po.custom_target(venue="kalshi", native_market_id="KXHIGHNY-26OCT04-B67.5",
                              at=KICKOFF - timedelta(hours=29)), "origin": "adr0030_decision"}
    adr["target_id"] = po.target_id(adr["market_id"], "post_decision_1h", _t(adr["target_utc"]))
    adr["phase"] = "post_decision_1h"
    for t, p in ((hi, "0.3311"), (adr, "0.3322")):
        store.plan_price_target({"planned_at_utc": po._iso(KICKOFF - timedelta(days=2)), **t})
        _row(store, run, t, status="CAPTURED", at=_t(t["target_utc"]), bid=p, ask=p)
    ids["exp001"] = [hi["target_id"], adr["target_id"]]
    if nfl:
        cutoff = po.nfl_decision_cutoff(po._iso(KICKOFF))
        t24 = _nfl_target("T-24h", KICKOFF - timedelta(hours=24, minutes=-2))
        t6 = _nfl_target("T-6h", KICKOFF - timedelta(hours=6, minutes=-2))
        t6_late = _nfl_target("T-6h", cutoff - timedelta(minutes=5))  # its attempt lands after the cutoff
        t60 = _nfl_target("T-60m", KICKOFF - timedelta(minutes=58))
        t60_crossed = _nfl_target("T-60m", KICKOFF - timedelta(minutes=50))
        t60_missed = _nfl_target("T-60m", KICKOFF - timedelta(minutes=45), deadline=timedelta(minutes=10))
        odd = _nfl_target("T-3h", KICKOFF - timedelta(hours=3))  # a horizon this code does not know
        manual = po.custom_target(venue="kalshi", native_market_id=TICKER, at=KICKOFF - timedelta(hours=10))
        for t in (t24, t6, t6_late, t60, t60_crossed, t60_missed, odd, manual):
            store.plan_price_target({"planned_at_utc": po._iso(KICKOFF - timedelta(days=2)), **t})
        _row(store, run, t24, status="CAPTURED", at=_t(t24["target_utc"]), bid="0.4411", ask="0.4433")
        _row(store, run, t6, status="CAPTURED", at=_t(t6["target_utc"]), bid="0.4455", ask="0.4477")
        _row(store, run, t6_late, status="CAPTURED", at=cutoff + timedelta(minutes=1), bid="0.6411", ask="0.6433")
        _row(store, run, t60, status="CAPTURED", at=_t(t60["target_utc"]), bid="0.6123", ask="0.6377")
        _row(store, run, t60_crossed, status="NOT_EXECUTABLE", at=_t(t60_crossed["target_utc"]),
             reason="BOOK_ANOMALY: crossed book: yes bid 0.6455 + no bid 0.4000 >= 1")
        _row(store, run, t60_missed, status="MISSED", reason="EXPIRED: last book yes 0.6455 was not refreshed")
        _row(store, run, odd, status="CAPTURED", at=_t(odd["target_utc"]), bid="0.6123", ask="0.6377")
        _row(store, run, manual, status="CAPTURED", at=_t(manual["target_utc"]), bid="0.6123", ask="0.6377")
        # a settlement read (one per game day): its reason summarises settled markets
        settle = {"target_id": po.target_id("kalshi:KXNFLGAME", "custom", KICKOFF + timedelta(hours=7)),
                  "venue": "kalshi", "market_id": "kalshi:KXNFLGAME", "native_market_id": "KXNFLGAME",
                  "event_id": "kalshi:KXNFLGAME:settled:2026-10-04", "native_event_id": "KXNFLGAME", "phase": "custom",
                  "target_utc": po._iso(KICKOFF + timedelta(hours=7)),
                  "due_from_utc": po._iso(KICKOFF + timedelta(hours=7) - po.EARLY),
                  "deadline_utc": po._iso(KICKOFF + timedelta(hours=7, minutes=9)), "policy_version": po.POLICY_VERSION,
                  "origin": po.NFL_ORIGIN, "decision_ref": None, "decision_as_of_utc": None, "close_time_utc": None,
                  "close_basis": po.CLOSE_SEMANTICS["kalshi"].basis, "planned_rules_sha256": None,
                  "detail": {"nfl_role": po.NFL_ROLE_SETTLEMENT, "game_date": "2026-10-04"}}
        store.plan_price_target({"planned_at_utc": po._iso(KICKOFF - timedelta(days=2)), **settle})
        _row(store, run, settle, status="NOT_EXECUTABLE", at=KICKOFF + timedelta(hours=7), side=None,
             reason="SETTLEMENT_METADATA_READ: 26 KXNFLGAME market(s) settled; NYG result yes 1.0000")
        ids.update(t24=t24["target_id"], t6=t6["target_id"], t6_late=t6_late["target_id"], t60=t60["target_id"],
                   t60_crossed=t60_crossed["target_id"], t60_missed=t60_missed["target_id"], odd=odd["target_id"],
                   manual=manual["target_id"], settle=settle["target_id"])
    store.finish_run(run, status="succeeded")
    return SnapshotStore.open_readonly(store.path), ids


def _t(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def test_market_history_withholds_nfl_label_books_and_keeps_pre_decision_books(tmp_path):
    store, ids = _obs_store(tmp_path)
    hist = {h["target_id"]: h for h in po.market_history(store, MARKET)}
    for key in ("t24", "t6"):
        h = hist[ids[key]]
        assert h["bid"] in ("0.4411", "0.4455") and h["ask"] and h["depth"] and "exp002_label" not in h, key
    for key in ("t6_late", "t60", "t60_crossed", "odd", "manual"):
        h = hist[ids[key]]
        assert not set(po.NFL_LABEL_FIELDS) & set(h) and h["exp002_label"].startswith("HIDDEN"), key
        assert h["snapshot_id"] is not None and h["collection_status"] and h["observed_at_utc"], key  # availability
    assert hist[ids["t60_crossed"]]["miss_reason"] == "BOOK_ANOMALY: withheld (EXP-002 label)"
    missed = hist[ids["t60_missed"]]
    assert missed["miss_reason"] == "EXPIRED: withheld (EXP-002 label)" and missed["collection_status"] == "MISSED"
    text = _scrub(json.dumps(list(hist.values())))
    for price in LABEL_PRICES:
        assert price not in text, price
    settle = po.market_history(store, "kalshi:KXNFLGAME")
    assert len(settle) == 1 and settle[0]["miss_reason"] == "SETTLEMENT_METADATA_READ: withheld (EXP-002 label)"
    assert "NYG result" not in _scrub(json.dumps(settle)) and settle[0]["exp002_label"].startswith("HIDDEN")


def test_status_reduces_nfl_label_miss_reasons_and_the_cli_shows_no_label(tmp_path, monkeypatch):
    store, ids = _obs_store(tmp_path)
    now = KICKOFF + timedelta(days=1)
    report = po.status(store, now=now, systemctl=lambda args: "x")
    misses = {m["target_id"]: m for m in report["recent_misses"]}
    assert misses[ids["t60_missed"]]["reason"] == "EXPIRED: withheld (EXP-002 label)"
    monkeypatch.setattr(po, "timer_states", lambda run=None: {})
    code, out = _run(cli.main, ["observe", "status", "--db", str(store.path), "--market", MARKET])
    assert code == 0
    for price in LABEL_PRICES:
        assert price not in out, price
    assert "0.4411" in out and "0.4455" in out  # T-24h and T-6h books before the cutoff stay


def test_exp001_and_adr0030_observations_are_exactly_unchanged(tmp_path, monkeypatch):
    store, ids = _obs_store(tmp_path)
    market = "kalshi:KXHIGHNY-26OCT04-B67.5"
    now = KICKOFF + timedelta(days=1)
    withheld = po.market_history(store, market)
    status = po.status(store, now=now, systemctl=lambda args: "x")
    monkeypatch.setattr(po, "nfl_label_withheld", lambda *a, **k: False)  # as if nothing were ever withheld
    assert po.market_history(store, market) == withheld
    unchanged = po.status(store, now=now, systemctl=lambda args: "x")
    assert {k: v for k, v in unchanged.items() if k != "recent_misses"} == {
        k: v for k, v in status.items() if k != "recent_misses"}  # only the NFL T-60m miss reason differs
    assert {h["target_id"] for h in withheld} == set(ids["exp001"])
    assert [h["bid"] for h in withheld] == ["0.3311", "0.3322"] and all("exp002_label" not in h for h in withheld)
    # and the whole status of a store with no NFL rows is untouched
    monkeypatch.undo()
    (tmp_path / "plain").mkdir()
    plain, _ = _obs_store(tmp_path / "plain", nfl=False)
    a = po.status(plain, now=now, systemctl=lambda args: "x")
    monkeypatch.setattr(po, "nfl_label_withheld", lambda *a, **k: False)
    assert a == po.status(plain, now=now, systemctl=lambda args: "x")


def test_the_nfl_rule_fails_closed_and_leaves_other_markets_alone():
    cutoff = po.nfl_decision_cutoff("2026-10-04T17:00:00Z")
    assert cutoff == datetime(2026, 10, 4, 11, 30, tzinfo=UTC)  # T-6h due 11:00Z + 30 min late tolerance
    t6 = _nfl_target("T-6h", KICKOFF - timedelta(hours=6))
    kw = dict(venue="kalshi", native_market_id=TICKER)
    assert not po.nfl_label_withheld(t6, at_utc=po._iso(cutoff), **kw)
    assert po.nfl_label_withheld(t6, at_utc=po._iso(cutoff + timedelta(seconds=1)), **kw)
    assert po.nfl_label_withheld(t6, at_utc="not a time", **kw)
    no_kickoff = {**t6, "detail": {**t6["detail"], "commence_utc": None}}
    assert po.nfl_label_withheld(no_kickoff, at_utc=po._iso(cutoff), **kw)
    assert not po.nfl_label_withheld(t6, at_utc=None, **kw)  # no receipt, no figure
    assert po.nfl_label_withheld(_nfl_target("T-60m", KICKOFF), at_utc=None, **kw)
    assert po.nfl_label_withheld(None, at_utc=None, **kw)  # a KXNFLGAME row without the planner's detail
    assert not po.nfl_label_withheld(None, venue="kalshi", native_market_id="KXHIGHNY-26OCT04-B67.5", at_utc=None)
    assert not po.nfl_label_withheld(None, venue="polymarket", native_market_id="KXNFLGAME-x", at_utc=None)


def test_any_kalshi_nfl_series_without_planner_detail_fails_closed(tmp_path):
    # A manual custom target on another Kalshi NFL series (KXNFLSPREAD-style) near kickoff: no stored horizon, so
    # its figures are withheld; a KXHIGHNY custom row in the same store is untouched.
    store = SnapshotStore(tmp_path / "spread.sqlite3")
    run = "SYNTHETIC-spread"
    store.start_run(run)
    spread = po.custom_target(venue="kalshi", native_market_id="KXNFLSPREAD-26OCT04ARINYG-NYG3",
                              at=KICKOFF - timedelta(minutes=58), native_event_id="KXNFLSPREAD-26OCT04ARINYG")
    hi = po.custom_target(venue="kalshi", native_market_id="KXHIGHNY-26OCT04-B67.5", at=KICKOFF - timedelta(hours=30))
    for t, p in ((spread, "0.6123"), (hi, "0.3311")):
        store.plan_price_target({"planned_at_utc": po._iso(KICKOFF - timedelta(days=2)), **t})
        _row(store, run, t, status="CAPTURED", at=_t(t["target_utc"]), bid=p, ask=p)
    store.finish_run(run, status="succeeded")
    ro = SnapshotStore.open_readonly(store.path)
    (row,) = po.market_history(ro, spread["market_id"])
    assert not set(po.NFL_LABEL_FIELDS) & set(row) and row["exp002_label"].startswith("HIDDEN")
    assert "0.6123" not in _scrub(json.dumps(row))
    (plain,) = po.market_history(ro, hi["market_id"])
    assert plain["bid"] == plain["ask"] == "0.3311" and "exp002_label" not in plain
    assert po.nfl_label_withheld(None, venue="kalshi", native_market_id="KXNFLSPREAD-x", at_utc=None)
    assert not po.nfl_label_withheld(None, venue="kalshi", native_market_id="KXHIGHNY-x", at_utc=None)
