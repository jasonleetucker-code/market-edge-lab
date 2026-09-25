"""Economic evidence · B: the EXP-003 payoff-scan result file on the Research tab (Economic Evidence v1).

Read-only: the newest `experiments/EXP-003-*/results/payoff_scan_*.json` by evaluation as-of, checked only with
`payoff_constraints.verify_result_provenance` against EXP-003's own evidence-use log; nothing is evaluated per
request and no page view writes anything. Fixtures copy the repository's EXP-003 into a temporary registry
(`sports_fixtures.payoff_registry`); the repository's files are never written.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import socket
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from edge_lab.dashboard import Config, make_app
from edge_lab.dashboard import data as d
from edge_lab.dashboard import sports_fixtures as sf
from edge_lab.dashboard.views import research

sys.path.insert(0, str(Path(__file__).resolve().parent / "browser"))
import fixture_states  # noqa: E402

NOW = sf.PAYOFF_NOW


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the dashboard attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def plain(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).replace("&#x27;", "'").replace("&lt;", "<").split())


def load(root: Path, now=NOW) -> d.Loaded:
    return d.Context(Config(experiments_root=root, clock=lambda: now)).economic_b


def body(root: Path, now=NOW) -> str:
    return research.family_b_body(load(root, now), now)


def test_the_committed_production_result_is_shown_and_its_sidecar_skipped(tmp_path):
    root = sf.payoff_registry(tmp_path)  # every committed file, as the repository holds them
    loaded = load(root)
    assert loaded.status == d.OK and loaded.value["state"] == "POPULATED"
    assert loaded.value["file"] == "payoff_scan_production_edge-backup-5q41yg5u.json"
    assert loaded.value["sidecar"] == "payoff_scan_production_edge-backup-5q41yg5u.source.json"
    assert loaded.value["unreadable"] == []  # the .source.json sidecar is metadata, never read as a result
    text = plain(body(root))
    for needle in ("Production store", "Sets 38", "incomplete 38", "Quotes invalid",
                   "store-provenance sidecar", "payoff_scan_production_edge-backup-5q41yg5u.source.json",
                   "eu-20c877aea7e2500aa5037daee75a8cd8", "As of Sep 25, 12:59 AM EDT",
                   "No size evaluated for this set", "exceeds 0:05:00 (stale)"):
        assert needle in text, needle
    assert "Not production evidence" not in text and "Positive claims 0" in text


def test_the_committed_laptop_result_is_shown_and_labelled_not_production(tmp_path):
    root = sf.payoff_registry(tmp_path, keep="payoff_scan_laptop_*")
    loaded = load(root)
    assert loaded.status == d.OK and loaded.value["state"] == "POPULATED"
    assert loaded.value["file"] == "payoff_scan_laptop_store_2026-09-22.json"
    assert loaded.value["verification"].startswith("verify_result_provenance")
    text = plain(body(root))
    for needle in ("PAYOFF RESEARCH — NOT A CAPTURED RESULT", "Laptop store · not production evidence",
                   "Not production evidence", "Proof completeness", "incomplete 2", "Proof incomplete",
                   "Claims (set × size)", "not evaluated 5", "no surplus even before fees 1",
                   "Settlement costs", "Settlement cost unknown", "Positive claims",
                   "INSUFFICIENT_DEPTH (complete capture offers 0 < 1)", "No surplus, even before fees",
                   "Orphan-leg exposure", "$0.49 worst-state loss", "As of Sep 22, 6:38 PM EDT",
                   "evidence-use event", "eu-374acc98ca83fac9d86ed28643e2bc54", "writes no evidence-use event"):
        assert needle in text, needle
    assert "k-ok" not in body(root)  # nothing green
    assert "$1.14" in text  # an all-in acquisition cost is a cost, not a surplus
    assert "−$0.49" not in text and "+$" not in text  # orphan exposure is an unsigned loss, never a signed figure


def test_the_newest_result_by_evaluation_as_of_wins_and_only_its_positive_claim_shows_a_figure(tmp_path):
    root = sf.payoff_registry(tmp_path, production=True, positive=True)
    loaded = load(root)
    assert loaded.status == d.OK and loaded.value["file"] == "payoff_scan_SYNTHETIC_production_2026-09-25.json"
    html = body(root)
    text = plain(html)
    assert "Production store" in text and "Not production evidence" not in text
    assert "Conditional full-fill surplus · not captured" in text
    assert "$0.03" in text and "conditional on every leg filling · not captured arbitrage" in text
    assert html.count("conditional on every leg filling") == 1  # one positive claim, one figure (claim-adjusted)
    # every other claim shows no figure: the surplus column is unavailable with its reason
    evaluations = sorted(loaded.value["result"]["report"]["evaluations"], key=lambda e: e["as_of_utc"], reverse=True)
    shown_rows = sum(len(e["sizes"]) for e in evaluations[:research.PAYOFF_ROWS_SHOWN])
    # (the unavailable marker carries its reason twice: title and aria-label)
    assert html.count("no positive claim: the evaluator made none at this size") == 2 * (shown_rows - 1)


def test_no_positive_figure_without_a_positive_claim(tmp_path):
    text = plain(body(sf.payoff_registry(tmp_path, keep="payoff_scan_laptop_*")))
    assert "Positive claims 0" in text and "Conditional full-fill surplus · not captured" not in text
    assert "−$1.06" not in text and "−$1.14" not in text  # before-fees and upper-bound surpluses never shown


def test_stale_empty_blocked_error_and_unavailable_states(tmp_path):
    stale = plain(body(sf.payoff_registry(tmp_path / "s"), NOW + timedelta(days=10)))
    assert "Result is stale" in stale and "older than 8 days" in stale and "Stale · not current" in stale
    fresh = load(sf.payoff_registry(tmp_path / "f"), NOW + timedelta(days=5))  # 5.3 days after its books
    assert fresh.value["state"] == "POPULATED"  # 8 days is the threshold
    empty = plain(body(sf.payoff_registry(tmp_path / "e", results=False)))
    assert "No EXP-003 result recorded yet" in empty
    blocked = plain(body(sf.payoff_registry(tmp_path / "b", slot_status="QUEUED")))
    assert "EXP-003 results not shown" in blocked and "QUEUED" in blocked and "Proof" not in blocked
    error = body(sf.payoff_registry(tmp_path / "x", tamper=True))
    assert "Family B unavailable (read error)" in plain(error) and "does not verify" in plain(error)
    assert 'role="alert"' in error and "Proof complete" not in plain(error)  # a tampered PROVEN is never shown
    unavailable = plain(research.family_b_body(d.Loaded(d.NO_DATA, message="no experiment registry configured"), NOW))
    assert "Not yet available" in unavailable


def test_a_newer_file_that_does_not_verify_is_an_error_not_a_silent_fallback(tmp_path):
    root = sf.payoff_registry(tmp_path, production=True)
    newest = next(root.glob("EXP-003-*/results/payoff_scan_SYNTHETIC_production_*.json"))  # the newest
    obj = json.loads(newest.read_text(encoding="utf-8"))
    obj["provenance"]["source_store"] = "production"
    obj["provenance"]["evidence_use_event_id"] = "eu-" + "0" * 32  # not in the log
    newest.write_text(json.dumps(obj), encoding="utf-8")
    loaded = load(root)
    assert loaded.status == d.ERROR and newest.name in loaded.message


def test_unreadable_files_and_the_file_bound(tmp_path, monkeypatch):
    root = sf.payoff_registry(tmp_path)
    results = next(root.glob("EXP-003-*/results"))
    (results / "payoff_scan_broken.json").write_text("{not json", encoding="utf-8")
    loaded = load(root)
    assert loaded.status == d.OK and any("payoff_scan_broken.json" in u for u in loaded.value["unreadable"])
    assert "payoff_scan_broken.json" in plain(body(root))
    monkeypatch.setattr(d, "PAYOFF_RESULT_MAX_FILES", 1)
    assert load(root).status == d.ERROR


def test_set_construction_and_hash_definition_come_from_the_helpers_with_legacy_notes(tmp_path):
    from edge_lab import payoff_constraints as pc
    legacy = sf.payoff_registry(tmp_path / "legacy")  # #103's production file predates both fields
    value = load(legacy).value
    assert value["set_construction"] == pc.LEGACY_SET_CONSTRUCTION and value["set_construction_legacy"]
    assert value["input_hash_definition"] == pc.LEGACY_INPUT_HASH_DEFINITION and value["input_hash_definition_legacy"]
    text = plain(body(legacy))
    assert f"set construction {pc.LEGACY_SET_CONSTRUCTION} (legacy)" in text
    assert f"input hash definition {pc.LEGACY_INPUT_HASH_DEFINITION} (legacy)" in text
    assert plain(research.PAYOFF_LEGACY_NOTE) in text and plain(research.PAYOFF_LEGACY_HASH_NOTE) in text
    current = sf.payoff_registry(tmp_path / "round", production=True)
    value = load(current).value
    assert (value["set_construction"], value["input_hash_definition"]) == (pc.SET_CONSTRUCTION, pc.INPUT_HASH_DEFINITION)
    text = plain(body(current))
    assert f"set construction {pc.SET_CONSTRUCTION}" in text and f"input hash definition {pc.INPUT_HASH_DEFINITION}" in text
    assert "mid-round anchor artifacts" not in text and "not comparable with a current-definition hash" not in text


def test_a_helper_that_raises_leaves_the_method_unknown_and_the_page_renders(tmp_path):
    from edge_lab import payoff_constraints as pc

    class Odd:  # payoff_constraints, except one helper that raises on this input
        def __getattr__(self, name):
            return getattr(pc, name)

        @staticmethod
        def input_hash_definition_of(obj):
            raise TypeError("odd mapping")

    methods = d.payoff_methods(Odd(), {"report": {}})
    assert methods["set_construction"] == pc.LEGACY_SET_CONSTRUCTION and methods["input_hash_definition"] is None
    assert methods["input_hash_definition_problem"] == "input_hash_definition_of could not read this file (TypeError)"
    assert not methods["input_hash_definition_legacy"]
    missing = d.payoff_methods(object(), {"report": {}})
    assert missing["set_construction"] is None and "not in this build" in missing["set_construction_problem"]
    view = {**load(sf.payoff_registry(tmp_path)).value, **methods}
    html = research._payoff_view(view, NOW)
    # the unavailable marker carries its reason (title and aria-label)
    assert "input_hash_definition_of could not read this file (TypeError)" in html
    assert plain(research.PAYOFF_LEGACY_HASH_NOTE) not in plain(html)  # no legacy note for an unknown definition


def test_a_verification_error_never_shows_the_logs_absolute_path(tmp_path):
    root = sf.payoff_registry(tmp_path)
    log = next(root.glob("EXP-003-*/evidence_use.jsonl"))
    with log.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("{not json\n")
    loaded = load(root)
    assert loaded.status == d.ERROR and "does not verify" in loaded.message
    assert "EvidenceError: evidence_use.jsonl:" in loaded.message  # the file is named ...
    assert str(tmp_path) not in loaded.message and str(log.parent) not in loaded.message  # ... never its path
    assert not re.search(r"[A-Za-z]:\\|/tmp/|/home/|/Users/", loaded.message), loaded.message


def test_a_symlinked_result_is_never_followed(tmp_path):
    root = sf.payoff_registry(tmp_path / "r", keep="payoff_scan_laptop_*")
    results = next(root.glob("EXP-003-*/results"))
    outside = tmp_path / "outside.json"
    shutil.copy(next(results.glob("payoff_scan_laptop_*.json")), outside)
    link = results / "payoff_scan_zz_link.json"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not permitted on this machine")
    loaded = load(root)
    assert loaded.status == d.OK and loaded.value["file"] == "payoff_scan_laptop_store_2026-09-22.json"
    assert any("payoff_scan_zz_link.json: not a plain file" in u for u in loaded.value["unreadable"])


def test_result_files_are_read_once_per_size_and_mtime_and_never_when_blocked(tmp_path, monkeypatch):
    reads = []
    real = Path.read_text

    def counting(self, *args, **kwargs):
        if self.name.startswith("payoff_scan_"):
            reads.append(self.name)
        return real(self, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", counting)
    blocked = sf.payoff_registry(tmp_path / "b", slot_status="QUEUED")
    reads.clear()
    assert load(blocked).value["state"] == "BLOCKED" and reads == []  # the slot decides before any read
    root = sf.payoff_registry(tmp_path / "r")
    reads.clear()
    load(root)
    first = sorted(reads)
    assert first and len(first) == len(set(first))
    load(root)
    assert sorted(reads) == first  # the second view read nothing
    results = next(root.glob("EXP-003-*/results"))
    changed = next(results.glob("payoff_scan_laptop_*.json"))
    changed.write_text(changed.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    reads.clear()
    load(root)
    assert reads == [changed.name]  # only the changed file is read again
    monkeypatch.setattr(d, "PAYOFF_RESULT_MAX_TOTAL_BYTES", 1000)
    over = load(root)
    assert over.status == d.ERROR and "over the Terminal's bound" in over.message


def test_a_future_evaluation_as_of_is_an_error_never_populated_forever(tmp_path):
    root = sf.payoff_registry(tmp_path)
    early = load(root, NOW.replace(hour=4))  # before the committed production result's newest evaluation
    assert early.status == d.ERROR and "later than now" in early.message
    assert load(root, NOW).status == d.OK
    # an as-of after the file's own generation time: re-hashed so only this check can fail
    from edge_lab import payoff_constraints as pc
    path = next(root.glob("EXP-003-*/results/payoff_scan_production_*.json"))
    obj = json.loads(path.read_text(encoding="utf-8"))
    prov = obj["provenance"]
    envelope = pc.result_envelope(obj["report"], generated_at_utc="2026-09-25T01:00:00+00:00",
                                  source_store=prov["source_store"], code_version=prov["code_version"],
                                  evidence_use_event_id=prov["evidence_use_event_id"])
    path.write_text(json.dumps(envelope), encoding="utf-8")
    late = load(root)
    assert late.status == d.ERROR and "later than its generation time" in late.message, late.message


def _size(**kw):
    return {"basket_quantity": "1", "evaluated": True, "states_skipped": [], "worst_state_surplus": "0.01",
            "claim": "NO_SURPLUS_AFTER_FEES", "claim_reasons": [], **kw}


def test_settlement_costs_come_from_structured_fields_never_reason_text():
    assert "Settlement cost unknown" in plain(research._payoff_settlement(_size(worst_state_surplus=None)))
    refund = plain(research._payoff_settlement(_size(worst_state_surplus=None, states_skipped=["VOID"])))
    assert "Refund unknown" in refund and "VOID not valued" in refund and "Settlement cost unknown" not in refund
    # the evaluator's wording is never parsed: this reason text changes nothing
    costed = plain(research._payoff_settlement(_size(claim_reasons=["settlement cost UNKNOWN"])))
    assert costed == "Costed by the evaluator"
    assert "not evaluated" in research._payoff_settlement(_size(evaluated=False))


def test_orphan_exposure_is_an_unsigned_loss_and_a_positive_claim_shows_only_its_adjusted_figure():
    text = plain(research._payoff_orphans(_size(orphan_exposure={"a/YES": "-0.49", "b/YES": "0.20", "c/YES": None})))
    assert text == "a/YES: $0.49 worst-state loss b/YES: no worst-state loss c/YES: unknown"
    positive = research._payoff_surplus(_size(claim=research.POSITIVE_CLAIM, claim_adjusted_surplus=None,
                                              worst_state_surplus="0.0400"))
    assert "$0.04" not in plain(positive) and "the evaluator stated no claim-adjusted figure" in positive


def test_the_forging_fixture_writes_only_to_temporary_copies(tmp_path):
    with pytest.raises(ValueError, match="writes only under"):
        sf.payoff_registry(sf.REPO_EXPERIMENTS.parent / "not-a-temp-dir")
    assert not (sf.REPO_EXPERIMENTS.parent / "not-a-temp-dir").exists()
    assert sf.payoff_registry(tmp_path / "ok").is_dir()  # pytest's tmp_path is under the system temp dir


def test_page_views_write_nothing_and_never_touch_the_repository(tmp_path):
    root = sf.payoff_registry(tmp_path)
    log = next(root.glob("EXP-003-*/evidence_use.jsonl"))
    before = hashlib.sha256(log.read_bytes()).hexdigest()
    repo_log = next((sf.REPO_EXPERIMENTS).glob("EXP-003-*/evidence_use.jsonl"))
    repo_before = hashlib.sha256(repo_log.read_bytes()).hexdigest()
    for _ in range(3):
        body(root)
    assert hashlib.sha256(log.read_bytes()).hexdigest() == before
    assert hashlib.sha256(repo_log.read_bytes()).hexdigest() == repo_before


@pytest.mark.parametrize("name", ["payoff", "payoff_laptop", "payoff_production"])
def test_the_research_tab_renders_section_b(name):
    cfg, root = fixture_states.BUILDERS[name]()
    try:
        out = {}
        page = b"".join(make_app(cfg)({"REQUEST_METHOD": "GET", "PATH_INFO": "/experiments", "QUERY_STRING": "",
                                       "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("s", s))).decode()
        assert out["s"] == "200 OK"
        part = page[page.index('aria-labelledby="ev-b-h"'):]
        text = plain(part[:part.index("</section>")])
        assert ("Production store" in text) == (name != "payoff_laptop")
        assert ("Not production evidence" in text) == (name == "payoff_laptop")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_gallery_shows_every_family_b_state():
    cfg, root = fixture_states.demo()
    out = {}
    page = b"".join(make_app(cfg)({"REQUEST_METHOD": "GET", "PATH_INFO": "/gallery", "QUERY_STRING": "",
                                   "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("s", s))).decode()
    assert out["s"] == "200 OK"
    for sid in ("g-evb-production", "g-evb-committed", "g-evb-laptop", "g-evb-states"):
        assert f'aria-labelledby="{sid}"' in page
    part = page[page.index('aria-labelledby="g-evb-states"'):]
    text = plain(part[:part.index("</section>")])
    for needle in ("Result is stale", "No EXP-003 result recorded yet", "EXP-003 results not shown",
                   "Family B unavailable (read error)", "Not yet available"):
        assert needle in text, needle
