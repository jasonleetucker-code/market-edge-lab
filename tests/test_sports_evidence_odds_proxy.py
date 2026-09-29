"""EXP-002 label proxy in the Family A report (PR D): a T-60m row's sportsbook consensus tracks the Kalshi T-60m book
that is E1's exit label, so a report that logs no label access withholds its Odds-derived figures (consensus
probabilities, dispersion, each side's consensus probability and tie-adjusted interval, the odds reasons' text).
The logged --with-results run shows them and records that it did. Checks use parsed fields, not substrings."""

from __future__ import annotations

import json
import re

import pytest

import test_sports_evidence_exp002 as t2
from edge_lab import odds_consensus as oc
from edge_lab import research_evidence as rev
from edge_lab import sports_evidence as se
from edge_lab.storage import SnapshotStore


def _leaves(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _leaves(v, f"{path}/{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _leaves(v, f"{path}[{i}]")
    else:
        yield path, value


@pytest.fixture
def built(tmp_path):
    return t2.build_store(tmp_path)


def test_the_plain_report_withholds_t60m_sportsbook_figures(built, tmp_path, capsys):
    path, now, _ = built
    root, own = t2._registry_copy(tmp_path)
    before = len(rev.read_log(own).uses)
    assert se.main(["report", "--db", str(path), "--as-of", now.isoformat(), "--experiments", str(root)]) == 0
    report = json.loads(capsys.readouterr().out)
    t60 = [r for r in report["rows"] if r["horizon"] == "T-60m" and r["odds"].get("received_utc")]
    assert t60
    for r in t60:
        assert not set(r["odds"]) & set(se.ODDS_PROXY_FIELDS) and r["odds"]["label_proxy"] == oc.LABEL_PROXY_HIDDEN
        # availability and timing stay: receipt, snapshot, hashes, status, book counts, freshness
        for key in ("received_utc", "snapshot_id", "input_sha256", "status", "contributing_books", "quoting_books",
                    "freshness_at_receipt"):
            assert key in r["odds"], key
        for side in r["sides"].values():
            assert not set(side) & set(se.SIDE_ODDS_PROXY_FIELDS)
            assert side["odds_label_proxy"] == oc.LABEL_PROXY_HIDDEN and "decision_freshness_odds" in side
    earlier = [r for r in report["rows"] if r["horizon"] in ("T-24h", "T-6h") and r["odds"].get("probabilities")]
    assert earlier and all("label_proxy" not in r["odds"] for r in earlier)  # pre-decision inputs stay
    assert all(s.get("consensus_probability") is not None for r in earlier for s in r["sides"].values()
               if s.get("stage") is None)
    assert len(rev.read_log(own).uses) == before  # nothing logged, nothing label-bearing shown

    # The logged run shows them (and records the view first); none of its T-60m figures is in a plain T-60m row.
    assert se.main(["report", "--db", str(path), "--as-of", now.isoformat(), "--experiments", str(root),
                    "--with-results", "--evidence-log", str(own), "--actor", "test", "--code-version", "abc"]) == 0
    logged = json.loads(capsys.readouterr().out)
    assert logged["evidence_use"] == "APPENDED" and len(rev.read_log(own).uses) == before + 1
    figures = {v for r in logged["rows"] if r["horizon"] == "T-60m"
               for v in (r["odds"].get("probabilities") or {}).values()}
    figures |= {s["consensus_probability"] for r in logged["rows"] if r["horizon"] == "T-60m"
                for s in r["sides"].values() if s.get("consensus_probability") is not None}
    assert figures
    horizon = {i: r["horizon"] for i, r in enumerate(report["rows"])}
    for path_, value in _leaves(report):
        m = re.match(r"/rows\[(\d+)\]", path_)
        if m and horizon[int(m.group(1))] != "T-60m":
            continue  # a pre-decision row may share a value with the synthetic T-60m capture
        assert not (isinstance(value, str) and value in figures), path_


def test_odds_reasons_keep_only_their_code_on_a_withheld_row():
    row = {"horizon": "T-60m", "commence_utc": "2026-09-27T17:00:00Z", "reasons": [
               "CONSENSUS_NOT_SUPPORTED: UNSUPPORTED ONE_SIDED: price -237 only", "KALSHI_BOOK_MISSING [X]: none"],
           "odds": {"received_utc": "2026-09-27T16:00:40Z", "stage": se.Stage.CONSENSUS_NOT_SUPPORTED,
                    "reasons": ["UNSUPPORTED ONE_SIDED: price -237 only"], "probabilities": {"X": "0.4"}},
           "sides": {"X": {"consensus_probability": "0.4", "stage": None}}}
    out = se._hide_odds_proxy(row)
    assert out["odds"]["reasons"] == [f"CONSENSUS_NOT_SUPPORTED: {oc.LABEL_PROXY_REASON}"]
    assert out["reasons"] == [f"CONSENSUS_NOT_SUPPORTED: {oc.LABEL_PROXY_REASON}", "KALSHI_BOOK_MISSING [X]: none"]
    assert "-237" not in json.dumps({**out, "odds": {**out["odds"], "stage": "x"}})
    early = {**row, "horizon": "T-6h", "odds": {**row["odds"], "received_utc": "2026-09-27T11:00:40Z"}}
    assert se._hide_odds_proxy(early) is early  # pre-decision: unchanged
    late = {**early, "odds": {**early["odds"], "received_utc": "2026-09-27T11:30:01Z"}}
    assert "probabilities" not in se._hide_odds_proxy(late)["odds"]  # after the T-6h cutoff (11:30Z)


def test_the_terminal_view_is_unaffected(built):
    path, now, _ = built
    view = se.terminal_view(path, now=now)["family_a"]
    assert view["capacity"]["latest"]["horizon"] != "T-60m"  # the Terminal shows pre-label books only (#124)
    rows = se.build_report(SnapshotStore.open_readonly(path), as_of=now)["rows"]
    assert any(r["horizon"] == "T-6h" and r["odds"].get("probabilities") for r in rows)
