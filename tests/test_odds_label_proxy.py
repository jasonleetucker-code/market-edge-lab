"""EXP-002 label proxy, The Odds API (PR D): a sportsbook capture of an NFL game at T-60m, or received after the
game's T-6h decision cutoff, tracks the Kalshi T-60m book that is EXP-002's label. Every display of it (the
`odds consensus` CLI and the Terminal's "Consensus at this capture") withholds its probabilities, prices, lines
and de-vigs; the pre-decision captures, statuses, times and counts stay. One rule, `odds_schedule.is_label_proxy`,
shared with the Polymarket US displays (#130)."""

from __future__ import annotations

import io
import json
import re
import shutil
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import pytest

from edge_lab import odds_consensus as oc
from edge_lab import odds_schedule as osch
from edge_lab import polymarket_sports as ps
from edge_lab.dashboard import make_app
from edge_lab.dashboard import data as d
from edge_lab.dashboard import fixtures
from edge_lab.dashboard import presentation as pr
from edge_lab.dashboard.views import research
from edge_lab.storage import SnapshotStore

sys.path.insert(0, str(Path(__file__).resolve().parent / "browser"))
import fixture_states  # noqa: E402

UTC = timezone.utc
KICK = "2026-09-25T00:15:00Z"  # the fixture's first game
FIRST = "fx000evt"


def plain(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def page(cfg) -> str:
    out = {}
    body = b"".join(make_app(cfg)({"REQUEST_METHOD": "GET", "PATH_INFO": "/experiments", "QUERY_STRING": "tab=sources",
                                   "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("status", s)))
    assert out["status"] == "200 OK"
    return body.decode("utf-8")


@pytest.fixture
def proxy():
    cfg, root = fixture_states.odds_label_proxy()
    yield cfg
    shutil.rmtree(root, ignore_errors=True)


def _snapshots(cfg) -> dict[str, int]:
    """offset -> stored odds snapshot id of the first game's captures."""
    store = SnapshotStore.open_readonly(cfg.db)
    return {r["offset_label"]: int(r["snapshot_id"]) for r in store.odds_targets(sport="americanfootball_nfl")
            if r["event_id"] == FIRST and r["state"] == "CAPTURED"}


def _unwithheld(cfg, offset: str) -> oc.EventConsensus:
    store = SnapshotStore.open_readonly(cfg.db)
    return oc.consensus_for_snapshot(store, _snapshots(cfg)[offset]).events[0]


def _percents(event: oc.EventConsensus) -> set[str]:
    """How the event's consensus and de-vigged probabilities render on the page (e.g. "70.31%")."""
    values = [o.consensus_probability for p in event.propositions for o in p.consensus]
    values += [x for p in event.propositions for b in p.books for x in b.probabilities]
    return {t for v in values if v is not None and (t := pr.percent(v))}


def _leaves(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _leaves(v, f"{path}/{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            yield from _leaves(v, f"{path}[{i}]")
    else:
        yield path, value


# --------------------------------------------------------------------------- the one rule


def test_the_decision_cutoff_is_the_odds_t6h_deadline():
    # Kickoff 00:15Z: T-6h at 18:15Z (14:15 ET, outside the quiet window) + the 30-min late tolerance.
    assert osch.decision_cutoff(KICK) == datetime(2026, 9, 24, 18, 45, tzinfo=UTC)
    assert osch.decision_cutoff(None) is None and osch.decision_cutoff("2026-09-25T00:15:00") is None  # naive
    target = osch.CaptureTarget("x", "s", "e", "T-6h", 2, datetime(2026, 9, 25, 0, 15, tzinfo=UTC),
                                datetime(2026, 9, 24, 18, 15, tzinfo=UTC))
    assert osch.decision_cutoff(KICK) == osch.deadline(target)
    # Polymarket US uses the same rule with its kickoff tolerance, and the Kalshi NFL observations (#131) with
    # none: neither keeps a copy of it.
    from edge_lab import price_observations as po

    assert po.NFL_PRE_DECISION_OFFSETS is osch.PRE_DECISION_OFFSETS and po.NFL_DECISION_OFFSET == osch.DECISION_OFFSET
    for start in ("2026-09-27T17:00:00Z", KICK, "2026-10-05T03:40:00Z"):
        assert ps.decision_cutoff(start) == osch.decision_cutoff(start, kickoff_tolerance=ps.START_TOLERANCE)
        assert po.nfl_decision_cutoff(start) == osch.decision_cutoff(start)


@pytest.mark.parametrize("offset,received,hidden", [
    ("T-24h", "2026-09-24T00:15:30Z", False),
    ("T-6h", "2026-09-24T18:15:41Z", False),
    ("T-6h", "2026-09-24T18:45:00Z", False),  # at the cutoff
    ("T-6h", "2026-09-24T18:45:01Z", True),
    ("T-60m", "2026-09-24T23:15:20Z", True),
    ("T-60m", None, True),
    ("T-3h", "2026-09-24T21:15:00Z", True),  # unknown horizon: fails closed
    ("T-6h", "not a time", True),
    ("T-6h", None, False),
])
def test_the_shared_rule(offset, received, hidden):
    assert osch.is_label_proxy(offset, KICK, received) is hidden
    assert osch.after_decision(None, "2026-09-24T18:00:00Z") is True  # an unknown kickoff fails closed


# --------------------------------------------------------------------------- the contract's display copy


def _row(sid: int, received: str, event: dict, *, sport: str = "americanfootball_nfl", targets=None) -> dict:
    from edge_lab.provenance import canonical_json, sha256_hex

    request = {"purpose": "capture", "odds_format": "american", "slot_id": "slot"}
    if targets is not None:
        request["targets"] = targets
    text = canonical_json({"sport": sport, "events": [event], "request": request})
    return {"id": sid, "fetched_at_utc": received, "url": "synthetic://odds", "payload_sha256": sha256_hex(text),
            "payload_json": text}


def _event(sport: str = "americanfootball_nfl", *, bad_price: bool = False) -> dict:
    def o(name, price, point=None):
        return {"name": name, "price": price, **({"point": point} if point is not None else {})}
    books = [{"key": f"book{i}", "last_update": "2026-09-24T18:14:00Z", "markets": [
        {"key": "h2h", "outcomes": [o("Home", -237), o("Away", 197)]},
        {"key": "spreads", "outcomes": [o("Home", -115, -6.5), o("Away", -105, 6.5)]}]} for i in range(3)]
    if bad_price:
        books[0]["markets"][0]["outcomes"][0]["price"] = "-2.37x"
    return {"id": "g1", "sport_key": sport, "home_team": "Home", "away_team": "Away", "commence_time": KICK,
            "bookmakers": books}


def test_a_pre_decision_capture_is_returned_unchanged():
    result = oc.build_snapshot_consensus(_row(1, "2026-09-24T18:15:41Z", _event()))
    assert oc.withhold_label_proxies(result) is result
    assert all("label_proxy" not in e for e in result.to_dict()["events"])  # omitted: hashes are unchanged
    assert oc.withhold_label_proxies(None) is None


def test_a_post_cutoff_capture_is_withheld_keeping_counts_and_times():
    full = oc.build_snapshot_consensus(_row(2, "2026-09-24T23:15:20Z", _event(bad_price=True)))
    shown = oc.withhold_label_proxies(full)
    e = shown.events[0]
    assert e.propositions == () and e.unsupported == ()
    assert e.label_proxy == {"state": oc.LABEL_PROXY_HIDDEN, "propositions": len(full.events[0].propositions),
                             "supported_propositions": len(full.events[0].propositions),
                             "unsupported_groups": len(full.events[0].unsupported)}
    assert (e.event_id, e.home_team, e.commence_time_utc, e.bookmaker_count, e.freshness_at_receipt) == (
        "g1", "Home", KICK, 3, full.events[0].freshness_at_receipt)
    assert shown.received_at_utc == full.received_at_utc and shown.input_sha256 == full.input_sha256
    assert any("-2.37x" in p for p in full.problems)  # the parser quotes an invalid price ...
    assert shown.problems == ("PARSE: g1: withheld (EXP-002 label proxy)",)  # ... the display keeps the code
    figures = {"-237", "197", "+197", "6.5", "-6.5", "-2.37x"}
    for path, value in _leaves(shown.to_dict()):  # parsed leaves; the sha256 hex fields are not searched
        if path.endswith("sha256"):
            continue
        assert str(value) not in figures and "-2.37x" not in str(value), path
    assert shown.output_sha256 != full.output_sha256  # re-sealed: the hash of what is shown


def test_other_sports_and_horizons():
    nba = oc.build_snapshot_consensus(_row(3, "2026-09-24T23:15:20Z", _event("basketball_nba"), sport="basketball_nba"))
    assert oc.withhold_label_proxies(nba) is nba  # outside EXP-002's scope
    early_but_t60m = oc.build_snapshot_consensus(_row(4, "2026-09-24T12:00:00Z", _event(), targets=[
        {"target_id": "t", "event_id": "g1", "offset": "T-60m", "target_utc": "2026-09-24T23:15:00Z"}]))
    assert oc.withhold_label_proxies(early_but_t60m).events[0].label_proxy is not None  # captured for T-60m
    unknown = oc.build_snapshot_consensus(_row(5, "2026-09-24T12:00:00Z", _event(), targets=[
        {"target_id": "t", "event_id": "g1", "offset": None, "target_utc": None}]))
    assert oc.withhold_label_proxies(unknown).events[0].label_proxy is not None  # unknown horizon fails closed


# --------------------------------------------------------------------------- the CLI


def _cli(argv: list[str]) -> tuple[int, str]:
    from edge_lab import cli

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


def _figures(artifact: dict) -> tuple[set[str], set[str]]:
    """(raw prices, lines) of every offered price in an artifact, from the parsed JSON."""
    prices, lines = set(), set()
    for snap in artifact["snapshots"]:
        for e in snap["events"]:
            for p in e.get("propositions", []):
                for o in p["offered"]:
                    prices.add(o["raw_price"])
                    if o["line"] is not None:
                        lines.add(o["line"])
    return prices, lines


def test_the_cli_withholds_the_t60m_capture(proxy):
    code, out = _cli(["odds", "consensus", "--db", str(proxy.db), "--event", FIRST])
    assert code == 0
    artifact = json.loads(out)
    by_sid = {s["snapshot_id"]: s for s in artifact["snapshots"]}
    sids = _snapshots(proxy)
    t6, t60 = by_sid[sids["T-6h"]]["events"][0], by_sid[sids["T-60m"]]["events"][0]
    assert t6["propositions"] and "label_proxy" not in t6
    assert t60["propositions"] == [] and t60["label_proxy"]["state"] == oc.LABEL_PROXY_HIDDEN
    assert t60["label_proxy"]["propositions"] == 3 and t60["bookmaker_count"] == 9
    prices, lines = _figures(artifact)
    assert "-180" in prices  # the T-6h prices stay
    assert not {"-237", "+197", "197"} & prices and not {"6.5", "-6.5", "41.5"} & lines
    hidden = {str(o.consensus_probability) for p in _unwithheld(proxy, "T-60m").propositions for o in p.consensus}
    printed = {o["consensus_probability"] for s in artifact["snapshots"] for e in s["events"]
               for p in e.get("propositions", []) for o in p["consensus"]}
    assert hidden and printed and not hidden & printed  # parsed fields, not substrings
    code, out = _cli(["odds", "consensus", "--db", str(proxy.db), "--since", "2026-09-24T00:00:00Z"])
    assert code == 0 and not {"-237", "197", "+197"} & _figures(json.loads(out))[0]
    code, out = _cli(["odds", "consensus", "--db", str(proxy.db), "--snapshot", str(sids["T-60m"])])
    assert code == 0 and json.loads(out)["snapshots"][0]["events"][0]["propositions"] == []


# --------------------------------------------------------------------------- the Terminal


def _rows(cfg) -> dict[str, d.OddsTarget]:
    ctx = d.Context(cfg)
    targets = ctx.odds_targets.value
    return {t.offset_label: t for t in (*targets.recent, *targets.upcoming) if t.event_id == FIRST}


def test_the_view_model_withholds_the_t60m_consensus(proxy):
    rows = _rows(proxy)
    t60 = rows["T-60m"].consensus.value
    assert t60.snapshot_id == _snapshots(proxy)["T-60m"]
    assert t60.events[0].propositions == () and t60.events[0].label_proxy["state"] == oc.LABEL_PROXY_HIDDEN
    t6 = rows["T-6h"].consensus.value
    assert t6.events[0].propositions and t6.events[0].label_proxy is None
    assert rows["T-60m"].state == "CAPTURED" and rows["T-60m"].offers == 54 and len(rows["T-60m"].books) == 9


def test_the_page_never_shows_the_t60m_figures(proxy):
    body = page(proxy)
    hidden = _percents(_unwithheld(proxy, "T-60m"))
    visible = _percents(_unwithheld(proxy, "T-6h"))
    assert hidden and visible and not hidden & visible  # distinctive values
    for figure in hidden | {"-237", "+197", "6.5", "41.5"}:
        assert figure not in body, figure
    assert any(v in body for v in visible)  # the T-6h consensus stays
    html = body[body.index('aria-labelledby="odds-t-h"'):]
    html = html[:html.index("</section>")]
    assert plain(html).count("Hidden · EXP-002 label proxy") >= 1
    assert 'title="code: ODDS_CAPTURE_LABEL_PROXY"' in html
    assert "k-ok" not in html[html.index("Hidden · EXP-002"):][:400]


def test_hiding_changes_figures_only(proxy, monkeypatch):
    hidden_body = page(proxy)
    monkeypatch.setattr(oc, "is_label_proxy_event", lambda *a, **k: False)
    d._CONSENSUS.clear()
    shown_body = page(proxy)
    leaked = _percents(_unwithheld(proxy, "T-60m"))
    assert any(v in shown_body for v in leaked)  # without the rule the fixture would leak
    pattern = r"(T-\d+[hm]) · kickoff"
    assert re.findall(pattern, plain(hidden_body)) == re.findall(pattern, plain(shown_body))
    for needle in (r"Books returned \d+ \d+ offers", r"Fresh at receipt", r"Captured"):
        found = re.findall(needle, plain(hidden_body))
        assert found and found == re.findall(needle, plain(shown_body)), needle
    d._CONSENSUS.clear()


@pytest.mark.parametrize("key", ["populated", "fresh", "fallback", "failed_closed", "none", "missing", "unavailable",
                                 "error"])
def test_the_other_consensus_states_are_unchanged(key):
    loaded, sid = fixtures.synthetic_consensus()[key]
    assert "EXP-002 label proxy" not in plain(research.consensus_body(loaded, sid))


def test_the_label_proxy_gallery_state():
    loaded, sid = fixtures.synthetic_consensus()["label_proxy"]
    html = research.consensus_body(loaded, sid)
    text = plain(html)
    assert "Hidden · EXP-002 label proxy" in text and "Propositions 3" in text and "Books quoting this event 3" in text
    full = oc.build_snapshot_consensus({**fixtures._consensus_row(
        908, [{**fixtures._consensus_event(mixed=False), "sport_key": "americanfootball_nfl"}]),
        "fetched_at_utc": fixtures.CONSENSUS_T60M})
    for figure in _percents(full.events[0]):
        assert figure not in html, figure


def test_the_browser_state_is_registered():
    assert fixture_states.BUILDERS["odds_label_proxy"] is fixture_states.odds_label_proxy
    assert fixture_states.ODDS_PROXY_NOW > datetime(2026, 9, 24, 23, 15, 20, tzinfo=UTC)  # after the T-60m capture
