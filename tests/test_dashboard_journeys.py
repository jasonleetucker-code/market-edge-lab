"""Operator journeys of Market v1 (docs/strategy/MARKET_V1_ACCEPTANCE.md §2): J1 setup/readiness, J4 wallet research,
J5 execution portfolio and J6 automation. Read-only pages that render real, empty, stale, missing, error, blocked,
paused and incomplete states honestly.

J5, J6 and the environments of J1 read the execution package's status export from the status directory (ADR 0043:
the dashboard imports nothing from that package). The exports here are written by the real exporter over FIXTURE
journals that the real orchestrator wrote against the test FakeVenue (`tests/browser/journey_fixtures.py`); other
states are those exports edited. J4 renders Demonstration A (SYNTHETIC) in demo mode only.
"""

from __future__ import annotations

import copy
import html as html_lib
import json
import re
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from edge_lab.dashboard import Config, make_app
from edge_lab.dashboard import data as d
from edge_lab.dashboard.views import ops_manifest as mf

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "browser"))

import journey_fixtures as jf  # noqa: E402

ROUTES = ("/setup", "/experiments/wallet", "/positions/execution", "/risk/automation")


def plain(body: str) -> str:
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", body)).split())


def get(cfg: Config, path: str) -> tuple[str, str]:
    out = {}
    body = b"".join(make_app(cfg)({"REQUEST_METHOD": "GET", "PATH_INFO": path, "HTTP_HOST": "127.0.0.1:8765"},
                                  lambda s, h: out.setdefault("status", s)))
    return out["status"], body.decode("utf-8")


def main(body: str) -> str:
    """The page's main content only (the shell's footer and navigation excluded)."""
    return body[body.index('<main id="main"'):body.index('<footer class="foot">')]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("journeys")
    return {s: jf.build(s, root / s) for s in jf.SCENARIOS}


def status_dir(tmp_path: Path, doc: dict | None, *, raw: str | None = None) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        (tmp_path / d.EXECUTION_STATUS_FILE).write_text(raw, encoding="utf-8")
    elif doc is not None:
        (tmp_path / d.EXECUTION_STATUS_FILE).write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


def cfg_for(built, scenario: str, *, later: timedelta = timedelta(minutes=1), demo: bool = False) -> Config:
    path, at = built[scenario]
    return Config(status_dir=path.parent, demo=demo, clock=lambda: at + later)


def doc_of(built, scenario: str) -> dict:
    return json.loads(built[scenario][0].read_text(encoding="utf-8"))


def page_text(cfg: Config, path: str) -> str:
    status, body = get(cfg, path)
    assert status == "200 OK", (path, status)
    return plain(main(body))


# ---------------------------------------------------------------- every route, both modes, no control


@pytest.mark.parametrize("demo", [False, True])
@pytest.mark.parametrize("path", ROUTES)
def test_every_journey_renders_read_only_in_both_modes(built, path, demo):
    status, body = get(cfg_for(built, "populated", demo=demo), path)
    assert status == "200 OK"
    for tag in ("<form", "<button", "<input", "<select", "<textarea"):
        assert tag not in body, (path, tag)
    assert "SHADOW · NO REAL MONEY" in body
    assert ("SYNTHETIC UI DEMO" in body) == demo
    text = plain(main(body))
    for _, label in (("/setup", "Setup & readiness"), ("/experiments/wallet", "Wallet research"),
                     ("/positions/execution", "Execution portfolio"), ("/risk/automation", "Automation")):
        assert label in text
    assert 'aria-current="page"' in body
    assert "k-ok" not in main(body)  # nothing is green: no fake connected or readiness badge


def test_the_routes_sit_under_existing_navigation(built):
    from edge_lab.dashboard.app import NAV_KEYS

    assert {p: NAV_KEYS[p] for p in ROUTES} == {"/setup": "more", "/experiments/wallet": "research",
                                                "/positions/execution": "portfolio", "/risk/automation": "risk"}
    _, body = get(cfg_for(built, "populated"), "/positions/execution")
    assert '<a href="/positions" aria-current="page">' in body  # the rail marks Portfolio


def test_a_post_is_refused(built):
    out = {}
    make_app(cfg_for(built, "populated"))({"REQUEST_METHOD": "POST", "PATH_INFO": "/risk/automation",
                                           "HTTP_HOST": "127.0.0.1"}, lambda s, h: out.setdefault("s", s))
    assert out["s"].startswith("405")


# ---------------------------------------------------------------- the export loader


def test_the_loader_states(tmp_path, built):
    now = built["populated"][1]
    cfg = Config(status_dir=None, clock=lambda: now)
    assert d.execution_status(d.Context(cfg)).status == d.NO_DATA
    cfg = Config(status_dir=status_dir(tmp_path / "none", None), clock=lambda: now)
    loaded = d.execution_status(d.Context(cfg))
    assert loaded.status == d.NO_DATA and "no executor has written" in loaded.message
    for name, raw in (("garbage", "{not json"), ("list", "[1, 2]"),
                      ("schema", json.dumps({"schema": "other/1"})),
                      ("bare", json.dumps({"schema": d.EXECUTION_STATUS_SCHEMA})),
                      ("hollow", json.dumps({"schema": d.EXECUTION_STATUS_SCHEMA, "environment": "FIXTURE",
                                             "environments": {}, "journal": {"state": "OK"}}))):
        cfg = Config(status_dir=status_dir(tmp_path / name, None, raw=raw), clock=lambda: now)
        assert d.execution_status(d.Context(cfg)).status == d.ERROR, name
    big = tmp_path / "big"
    big.mkdir()
    (big / d.EXECUTION_STATUS_FILE).write_text(" " * (d.EXECUTION_STATUS_MAX_BYTES + 1), encoding="utf-8")
    assert d.execution_status(d.Context(Config(status_dir=big, clock=lambda: now))).status == d.ERROR
    ok = d.execution_status(d.Context(cfg_for(built, "populated")))
    assert ok.status == d.OK and ok.value.export_freshness == "FRESH"
    stale = d.execution_status(d.Context(cfg_for(built, "populated", later=timedelta(hours=1))))
    assert stale.value.export_freshness == "STALE"
    future = d.execution_status(d.Context(cfg_for(built, "populated", later=-timedelta(hours=1))))
    assert future.value.export_freshness == "UNKNOWN"


# ---------------------------------------------------------------- J5 execution portfolio


def test_j5_populated_is_fixture_labelled_and_complete(built):
    text = page_text(cfg_for(built, "populated"), "/positions/execution")
    assert "Access not connected" in text and "No real account is connected" in text
    assert "Authorized environments in code (from the export): FIXTURE" in text
    assert "FIXTURE · fake venue · not a real account" in text
    assert "Reconciled at export" in text
    assert "$97.333612" in text and "available after venue holds" in text
    assert "Reserved $4.33" in text and "worst case of 2 held reservations" in text
    assert "KXHIGHNY-26OCT08-B72 YES · FIXTURE venue 4" in text
    assert "Outcome unknown · reserved" in text and "SEND_AMBIGUOUS" in text
    assert "4 of 8 filled · partial" in text
    assert "Attributed fills" in text and "Recorded settlements" in text
    assert "Realized total +$1.06" in text and "Unrealized —" in text
    assert "approval nonces" in text  # what the export leaves out, said in Details


def test_j5_never_colours_fixture_money(built):
    _, body = get(cfg_for(built, "populated"), "/positions/execution")
    assert 'class="num pos"' not in main(body) and 'class="num neg"' not in main(body)


def test_j5_missing_export_is_not_an_empty_portfolio(tmp_path, built):
    now = built["populated"][1]
    for cfg in (Config(clock=lambda: now), Config(status_dir=status_dir(tmp_path, None), clock=lambda: now)):
        text = page_text(cfg, "/positions/execution")
        assert "No execution export" in text and "This is not an empty portfolio" in text
        assert "No FIXTURE positions" not in text and "$0" not in text
        assert "Access not connected" in text and "EXECUTION_PLAN records FIXTURE only" in text


@pytest.mark.parametrize("edit,expect", [
    (lambda doc: doc.update(schema="edge-lab-execution-status/0"), "Execution export unavailable"),
    (lambda doc: doc.update(environment="PRODUCTION"), "Export refused: environment not shown here"),
    (lambda doc: doc.pop("control"), "Execution export unavailable"),
])
def test_j5_error_states(tmp_path, built, edit, expect):
    doc = doc_of(built, "populated")
    edit(doc)
    cfg = Config(status_dir=status_dir(tmp_path, doc), clock=lambda: built["populated"][1])
    for path in ("/positions/execution", "/risk/automation"):
        text = page_text(cfg, path)
        assert expect in text
        assert "$97.333612" not in text and "KXHIGHNY" not in text


EXPORT_PAGES = ("/positions/execution", "/risk/automation", "/setup")


def test_m2_an_export_claiming_production_is_refused_everywhere(tmp_path, built):
    """Review M2: the Terminal's own allowlist decides, never the export's `authorized` list."""
    doc = doc_of(built, "populated")
    doc["environment"] = "PRODUCTION"
    doc["scope_key"] = "PRODUCTION:real-acct:primary"
    doc["environments"]["authorized"] = ["FIXTURE", "PRODUCTION"]  # the export vouches for itself
    for row in doc["environments"]["rows"]:
        row["authorized"] = True
    cfg = Config(status_dir=status_dir(tmp_path, doc), clock=lambda: built["populated"][1])
    for path in EXPORT_PAGES:
        text = page_text(cfg, path)
        assert "Export refused: environment not shown here" in text, path
        assert "$97.333612" not in text and "KXHIGHNY" not in text and "Bounded auto" not in text
        assert "PRODUCTION · real money" not in text
    assert "As documented: only FIXTURE is authorized" in page_text(cfg, "/setup")


def test_m2_an_authorized_list_that_differs_from_the_terminal_is_a_mismatch(tmp_path, built):
    doc = doc_of(built, "populated")
    doc["environments"]["authorized"] = ["DEMO", "FIXTURE"]
    cfg = Config(status_dir=status_dir(tmp_path, doc), clock=lambda: built["populated"][1])
    for path in EXPORT_PAGES:
        text = page_text(cfg, path)
        assert "Authorized environments do not match" in text and "$97.333612" not in text, path


@pytest.mark.parametrize("path,value", [
    (("control", "open_incidents"), None),
    (("control", "open_incidents"), "reconciliation-lost:1"),
    (("control",), "DISARMED"),
    (("account", "snapshot"), "revision 8"),
    (("account", "reservations", "held"), [1, 2]),
    (("attempts", "rows"), {"a": 1}),
    (("journal", "chain_ok"), "yes"),
    (("environments", "authorized"), "FIXTURE"),
    (("journal",), "OK"),
    (("pnl", "by_market"), None),
])
def test_l1_l5_a_malformed_shape_is_an_error_state_not_a_crash(tmp_path, built, path, value):
    doc = doc_of(built, "paused")
    target = doc
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    loaded = d.execution_status(d.Context(Config(status_dir=status_dir(tmp_path, doc), clock=lambda: built["paused"][1])))
    assert loaded.status == d.ERROR and "malformed" in loaded.message and ".".join(path) in loaded.message
    cfg = Config(status_dir=tmp_path, clock=lambda: built["paused"][1])
    for page in EXPORT_PAGES:
        status, body = get(cfg, page)
        assert status == "200 OK", page
        text = plain(main(body))
        assert "Execution export unavailable" in text and "No control action is pending" not in text


def test_l1_unknown_incidents_never_read_as_nothing_pending(built):
    from edge_lab.dashboard.views import ops_automation

    doc = doc_of(built, "populated")
    doc["control"]["open_incidents"] = None
    text = plain(ops_automation.next_action(doc))
    assert "Stop reasons unknown" in text and "No control action is pending" not in text


def test_l2_unknown_chain_verification_is_the_unknown_marker(tmp_path, built):
    doc = doc_of(built, "idle")
    doc["journal"].update(chain_ok=None, chain_events=None)
    cfg = Config(status_dir=status_dir(tmp_path, doc), clock=lambda: built["idle"][1])
    _, body = get(cfg, "/positions/execution")
    text = plain(main(body))
    assert "NOT verified" not in text and "None events" not in text
    assert 'aria-label="chain verification not recorded"' in body
    assert "Journal chain verification not recorded" in text


def test_l3_truncated_lists_say_how_much_was_left_out(tmp_path, built):
    doc = doc_of(built, "populated")
    assert doc["attempts"]["unknown_omitted"] == 0 and doc["attempts"]["in_flight_omitted"] == 0
    assert doc["journal"]["chain_problems_omitted"] == 0
    doc["attempts"].update(unknown_omitted=3, rows_omitted=7)
    doc["attribution"]["rows_omitted"] = 2
    doc["settlements"]["rows_omitted"] = 4
    doc["control"]["refusals_omitted"] = 5
    cfg = Config(status_dir=status_dir(tmp_path, doc), clock=lambda: built["populated"][1])
    text = page_text(cfg, "/positions/execution")
    for note in ("3 older unknown or in-flight attempts are not in the export", "7 older attempts are not in the export",
                 "2 older attributed fills are not in the export", "4 older settlements are not in the export"):
        assert note in text, note
    doc["control"]["last_refusals"] = [{"mode": "SHADOW", "operator_ref": "owner", "at_utc": None, "reasons": ["x"]}]
    status_dir(tmp_path, doc)
    assert "5 older refusals are not in the export" in page_text(cfg, "/risk/automation")


def test_l4_fixture_labels_follow_the_environment_not_a_name(tmp_path, built):
    doc = doc_of(built, "populated")
    doc["control"]["armed_grant"]["summary"]["issuer_ref"] = "EXECUTION_PLAN-2026-10-08-owner-grant"
    doc["limits"]["owner_approval_ref"] = "EXECUTION_PLAN-2026-10-08-owner-limits"
    cfg = Config(status_dir=status_dir(tmp_path, doc), clock=lambda: built["populated"][1])
    text = page_text(cfg, "/risk/automation")
    assert "Armed grant · FIXTURE, not owner-set" in text and "FIXTURE limits · not owner-set" in text
    assert "Owner approval recorded" not in text
    assert "FIXTURE limits · not owner-set" in page_text(cfg, "/setup")


def test_j5_journal_states(tmp_path, built):
    now = built["populated"][1]
    jf.missing_journal(tmp_path / "nj", now=now)
    text = page_text(Config(status_dir=tmp_path / "nj", clock=lambda: now), "/positions/execution")
    assert "No execution journal" in text and "unknown, not empty" in text
    doc = doc_of(built, "no_config")
    for key in ("control", "account", "attempts"):
        doc.pop(key)
    doc["journal"] = {"state": "ERROR", "detail": "JournalCorrupt: control event at seq 4 does not decode"}
    text = page_text(Config(status_dir=status_dir(tmp_path / "je", doc), clock=lambda: now), "/positions/execution")
    assert "Execution journal unreadable" in text and "JournalCorrupt" in text


def test_j5_stale_export_is_never_current(built):
    text = page_text(cfg_for(built, "populated", later=timedelta(hours=2)), "/positions/execution")
    assert "Stale export — not current" in text and "every figure below is as of then, not now" in text
    assert "Execution export · FIXTURE" not in text


def test_j5_empty_account_is_known_empty(built):
    text = page_text(cfg_for(built, "idle"), "/positions/execution")
    assert "No FIXTURE positions" in text and "The latest snapshot was read and lists no position" in text
    assert "No FIXTURE orders" in text and "No settlement recorded" in text
    assert "Paused · no new risk" not in text


def test_j5_unknown_holdings_and_paused_and_incomplete(tmp_path, built):
    text = page_text(cfg_for(built, "paused"), "/positions/execution")
    assert "Reconciliation incomplete — holdings may be wrong" in text
    assert "Paused · no new risk" in text and "1 open incident" in text and "1 new-risk latch" in text
    assert "basis unknown: blocks new risk" in text
    assert "Cash —" in text and "Usable cash —" in text  # unknown cash is the marker, never $0.00
    doc = doc_of(built, "idle")
    doc["account"].update(snapshot=None, positions=None, external_orders=None)
    text = page_text(Config(status_dir=status_dir(tmp_path, doc), clock=lambda: built["idle"][1]),
                     "/positions/execution")
    assert "No account snapshot yet — holdings unknown" in text and "Holdings unknown" in text
    assert "No FIXTURE positions" not in text


def test_j5_partial_exit_and_untrusted_text_is_escaped(tmp_path, built):
    doc = doc_of(built, "populated")
    row = copy.deepcopy(doc["attempts"]["rows"][1])
    row.update(kind="REDUCTION", quantity="5", filled_quantity="2", partial=True, state="OUTCOME_UNKNOWN",
               state_reason="<script>x</script>")
    doc["attempts"]["rows"].insert(0, row)
    doc["attempts"]["unknown"].append(row)
    doc["attempts"]["partial_reductions"] = 1
    doc["account"]["external_orders"] = [{"origin": "MANUAL", "market_ticker": "KXHIGHNY-26OCT08-B70", "side": "yes",
                                          "action": "sell", "remaining_quantity": "2", "unreflected_cash": None}]
    _, body = get(Config(status_dir=status_dir(tmp_path, doc), clock=lambda: built["populated"][1]),
                  "/positions/execution")
    assert "<script>x" not in body and "&lt;script&gt;" in body
    assert "Partial exits 1" in plain(main(body))
    assert "Open orders not placed by the executor (1)" in plain(main(body))


def test_j5_unknown_and_resting_orders_survive_row_truncation(tmp_path, built):
    doc = doc_of(built, "populated")
    doc["attempts"].update(rows=doc["attempts"]["rows"][:0], rows_omitted=5)  # every row cut from the shown list
    text = page_text(Config(status_dir=status_dir(tmp_path, doc), clock=lambda: built["populated"][1]),
                     "/positions/execution")
    assert "Outcome unknown · reserved" in text and "4 of 8 filled · partial" in text
    assert "Partly filled orders 1" in text and "No FIXTURE orders" not in text


# ---------------------------------------------------------------- J6 automation


def test_j6_armed_grant_is_labelled_test(built):
    text = page_text(cfg_for(built, "populated"), "/risk/automation")
    assert "Bounded auto · inside a grant" in text and "Reconciled" in text
    assert "Armed grant · FIXTURE, not owner-set" in text and "TEST-FIXTURE-GRANT-not-an-owner-grant" in text
    assert "FIXTURE limits · not owner-set" in text and "Approval reference: test-fixture-only-not-owner" in text
    assert "Armed in BOUNDED_AUTO" in text and "DEMO_MODE_NEEDS_DEMO_SCOPE" in text
    assert "No open incident or latch" in text
    assert "Rearm procedure" in text and "cannot arm, disarm, approve, cancel or send anything" in text


def test_j6_paused_names_stop_reasons_and_next_action(built):
    text = page_text(cfg_for(built, "paused"), "/risk/automation")
    assert "Disarmed · no new risk" in text and "Reconciliation failed" in text
    assert "Acknowledge the open incidents" in text and "reconciliation-lost:" in text
    assert "reconciliation FAILED while in SHADOW or a sending mode" in text
    assert "MARKET: KXHIGHNY-26OCT08-B72" in text and "operator: thin book" in text
    assert "Recent refused arm requests" in text and "No grant armed" in text


def test_j6_unknown_limits_and_placeholders(tmp_path, built):
    text = page_text(cfg_for(built, "no_config"), "/risk/automation")
    assert "Limits unknown here" in text and "Configured grants: unknown" in text
    assert "Nothing is armed" in text
    doc = doc_of(built, "idle")
    doc["limits"].update(placeholder=True, owner_approval_ref=None)
    doc["grants"]["configured"] = []
    text = page_text(Config(status_dir=status_dir(tmp_path, doc), clock=lambda: built["idle"][1]), "/risk/automation")
    assert "Placeholder limits · refuse every order" in text and "No grant is configured" in text


def test_j6_missing_export(built):
    text = page_text(Config(clock=lambda: built["idle"][1]), "/risk/automation")
    assert "No execution export" in text and "Rearm procedure" in text and "Disarmed" not in text


# ---------------------------------------------------------------- J1 setup and readiness


def _norm(text: str) -> str:
    return " ".join(text.split())


def test_j1_manifest_is_pinned_to_its_sources():
    docs = {}
    for item in mf.ITEMS:
        text = docs.setdefault(item.source, _norm((REPO / item.source).read_text(encoding="utf-8")))
        assert _norm(item.quote) in text, (item.item_id, item.source)
        assert item.next_step and item.who and item.state in mf.STATE_WORDS and item.kind in dict(mf.KINDS)
    acceptance = _norm((REPO / mf.ACCEPTANCE).read_text(encoding="utf-8"))
    for name, state, quote in mf.TRACKS:
        assert _norm(quote) in acceptance and name in quote and state in quote
    plan = _norm((REPO / mf.PLAN).read_text(encoding="utf-8"))
    assert mf.DOCUMENTED_AUTHORIZED_QUOTE in plan
    ledger = (REPO / mf.LEDGER).read_text(encoding="utf-8")
    facts = ledger[ledger.index("## Facts that must be confirmed"):]
    facts = facts[:facts.index("\n## ", 5)] if "\n## " in facts[5:] else facts
    bullets = [line for line in facts.splitlines() if line.startswith("- **")]
    pinned = [i for i in mf.ITEMS if i.source == mf.LEDGER]
    assert len(bullets) == len(pinned), "a ledger fact was added or removed: update ops_manifest"
    packet = (REPO / mf.PACKET).read_text(encoding="utf-8")
    decisions = re.findall(r"^## Decision (\d)", packet, flags=re.M)
    covered = {i.item_id.split("-")[1] for i in mf.ITEMS if i.item_id.startswith("decision-")}
    assert set(decisions) == covered, "an activation-packet decision is not in the manifest"


def test_j1_from_the_export(built):
    text = page_text(cfg_for(built, "populated"), "/setup")
    assert "from the execution export" in text
    assert "FIXTURE fake transport and a disposable store; no real account Authorized · offline only" in text
    assert "DEMO egress (mock funds)" in text and "PRODUCTION reads and orders (real money)" in text
    assert "FIXTURE limits · not owner-set" in text
    for item in mf.ITEMS:
        assert item.title in text and item.next_step in text
    for name, _, _ in mf.TRACKS:
        assert name in text


def test_j1_without_an_export_shows_the_documented_authority(tmp_path, built):
    text = page_text(Config(status_dir=status_dir(tmp_path, None), clock=lambda: built["idle"][1]), "/setup")
    assert "No execution export" in text and "code value unknown" in text
    assert "As documented: only FIXTURE is authorized" in text and "Unknown here" in text
    text = page_text(cfg_for(built, "populated", later=timedelta(hours=3)), "/setup")
    assert "Stale export — not current" in text and "still the code's value at that time" in text


def test_j1_placeholder_limits(tmp_path, built):
    doc = doc_of(built, "idle")
    doc["limits"].update(placeholder=True)
    text = page_text(Config(status_dir=status_dir(tmp_path, doc), clock=lambda: built["idle"][1]), "/setup")
    assert "Placeholders · refuse every order" in text


# ---------------------------------------------------------------- J4 wallet research


def test_j4_production_is_blocked_and_shows_no_synthetic_figure(built):
    text = page_text(cfg_for(built, "populated"), "/experiments/wallet")
    assert "No wallet source is approved" in text and "Research only · no execution" in text
    assert "synthetic_venue" not in text and "Follower net" not in text and "SYNTHETIC research" not in text


def test_j4_demo_is_synthetic_everywhere(built):
    status, body = get(cfg_for(built, "populated", demo=True), "/experiments/wallet")
    assert status == "200 OK"
    m = main(body)
    sections = re.findall(r'<section class="section[^"]*" aria-labelledby="(wl-[a-z]+)"', m)
    assert set(sections) == {"wl-cov", "wl-sel", "wl-res", "wl-cat", "wl-unc", "wl-bench", "wl-copy"}
    for sid in sections:
        part = m[m.index(f'aria-labelledby="{sid}"'):]
        part = part[:part.index("</section>")]
        assert sid == "wl-copy" or "SYNTHETIC · not evidence" in plain(part), sid
    text = plain(m)
    assert "SYNTHETIC research demonstration — not evidence" in text
    assert "Selection date" in text and "Point-in-time selection manifest" in text
    assert "Follower net" in text and "Leader, scaled to follower" in text and "90% cluster bootstrap interval" in text
    assert "Category fit of eligible leaders" in text and "interval" in text
    assert "fees UNKNOWN: net economics blocked" in text  # the unknown-fee variant stays unknown
    assert 'class="num pos"' not in m and 'class="num neg"' not in m


def test_j4_demo_states(monkeypatch, built):
    cfg = cfg_for(built, "populated", demo=True)
    monkeypatch.setattr(d, "WALLET_DEMO_MODULE", "edge_lab.wallet_intel.not_a_module")
    assert "NO DATA / NOT STARTED" in page_text(cfg, "/experiments/wallet")
    monkeypatch.undo()
    from edge_lab.wallet_intel import demo

    report = copy.deepcopy(demo.run_synthetic_demo(d.WALLET_DEMO_SEED))
    monkeypatch.setattr(d, "_wallet_report", lambda module, seed: {**report, "data_class": "OBSERVED"})
    assert "does not label itself SYNTHETIC" in page_text(cfg, "/experiments/wallet")

    def boom(module, seed):
        raise RuntimeError("synthetic universe failed")
    monkeypatch.setattr(d, "_wallet_report", boom)
    text = page_text(cfg, "/experiments/wallet")
    assert "Data unavailable" in text and "synthetic universe failed" in text
    empty = copy.deepcopy(report)
    for record in empty["eligibility"]["manifest"]["records"]:
        record["status"] = "INELIGIBLE"
    empty["difference"]["cluster_bootstrap_90"] = None
    monkeypatch.setattr(d, "_wallet_report", lambda module, seed: empty)
    text = page_text(cfg, "/experiments/wallet")
    assert "No leader eligible at the selection date" in text and "Eligible 0 of 7" in text
    assert "Difference interval: not computed" in text and "no eligible leader, so no category fit" in text
