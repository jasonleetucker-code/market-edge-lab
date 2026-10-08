"""The execution status export (`execution/status_export.py`): the sanitized, versioned projection the operator
Terminal reads instead of importing the package (ADR 0043). FIXTURE only: every journal here is written by the real
orchestrator against the test FakeVenue (`tests/browser/journey_fixtures.py`)."""

from __future__ import annotations

import ast
import json
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "browser"))

import journey_fixtures as jf  # noqa: E402
import test_orchestrator_harness as h  # noqa: E402
from edge_lab.execution import control as ctl  # noqa: E402
from edge_lab.execution import status_export as se  # noqa: E402
from edge_lab.execution.journal import ExecutionJournal  # noqa: E402

SRC = Path(se.__file__).resolve()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _walk(value, path="$"):
    yield path, value
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk(v, f"{path}[{i}]")


@pytest.fixture(scope="module")
def exports(tmp_path_factory):
    root = tmp_path_factory.mktemp("exports")
    return {s: (jf.build(s, root / s), root / s) for s in jf.SCENARIOS}


def test_the_projection_is_versioned_and_labelled_fixture(exports):
    for scenario, ((path, _), _) in exports.items():
        doc = _load(path)
        assert doc["schema"] == se.SCHEMA == "edge-lab-execution-status/1", scenario
        assert doc["environment"] == "FIXTURE" and doc["scope_key"].startswith("FIXTURE:")
        assert doc["environments"]["authorized"] == ["FIXTURE"]
        assert [r["environment"] for r in doc["environments"]["rows"] if not r["authorized"]] == ["DEMO", "PRODUCTION"]
        assert doc["journal"]["state"] == "OK" and doc["journal"]["chain_ok"] is True
        assert path.name == se.FILENAME


def test_no_float_anywhere_and_money_is_exact_text(exports):
    (path, _), _ = exports["populated"]
    doc = _load(path)
    assert not [p for p, v in _walk(doc) if isinstance(v, float)]
    snap = doc["account"]["snapshot"]
    assert isinstance(snap["cash"], str) and Decimal(snap["cash"]) > 0
    for row in doc["attempts"]["rows"]:
        for name in ("quantity", "limit_price", "filled_quantity"):
            assert isinstance(row[name], str), (name, row)
    assert isinstance(doc["pnl"]["realized_total"], str)
    for row in doc["settlements"]["rows"]:
        assert isinstance(row["revenue"], str) and isinstance(row["yes_total_cost"], str)
    for row in doc["attribution"]["rows"]:
        assert isinstance(row["notional"], str) and isinstance(row["fees_known"], str)
    assert doc["account"]["reservations"]["held_cash_worst_case_total"] == "4.33"


def test_the_populated_journey_carries_every_section(exports):
    (path, _), _ = exports["populated"]
    doc = _load(path)
    assert doc["control"]["mode"] == "BOUNDED_AUTO" and doc["control"]["armed_grant"]["found_in_config"] is True
    assert doc["control"]["armed_grant"]["summary"]["issuer_ref"].startswith("TEST-FIXTURE-GRANT")
    assert doc["attempts"]["by_state"]["OUTCOME_UNKNOWN"] == 1 and len(doc["attempts"]["unknown"]) == 1
    assert any(r["partial"] for r in doc["attempts"]["rows"])  # the resting GTC, 4 of 8 filled
    assert doc["account"]["positions"] == [{"market_ticker": "KXHIGHNY-26OCT08-B72", "quantity": "4", "side": "yes"}]
    assert doc["settlements"]["count"] == 1 and doc["attribution"]["count"] == 3
    assert doc["pnl"]["baseline_recorded"] is True and doc["pnl"]["unrealized"] is None
    assert doc["cycles"]["count"] >= 1 and doc["cycles"]["last"]["schema_known"] is True
    assert doc["service"]["state"] == "STARTED_NO_SHUTDOWN_RECORDED"
    assert doc["limits"]["placeholder"] is False and doc["bounds"]["max_intents_per_cycle"] == 3
    modes = {r["mode"]: r for r in doc["control"]["arm_readiness"]}
    assert set(modes) == {m.value for m in ctl.Mode} - {"DISARMED"}
    assert modes["DEMO"]["reasons"] == ["DEMO_MODE_NEEDS_DEMO_SCOPE"]


def test_the_paused_journey_names_incidents_latches_and_refusals(exports):
    (path, _), _ = exports["paused"]
    doc = _load(path)
    c = doc["control"]
    assert c["mode"] == "DISARMED" and c["reconciliation"] == "FAILED"
    (incident,) = c["open_incidents"]
    assert incident["incident_id"].startswith("reconciliation-lost:") and incident["reason"]
    assert c["latches"] == [{"key": "KXHIGHNY-26OCT08-B72", "reason": "operator: thin book", "scope": "MARKET",
                             "set_at_utc": c["latches"][0]["set_at_utc"]}]
    assert c["last_refusals"][0]["reasons"][0].startswith("RECONCILIATION_NOT_COMPLETE")
    blocked = {r["mode"]: r["reasons"] for r in c["arm_readiness"]}
    assert any(x.startswith("INCIDENTS_NOT_ACKNOWLEDGED") for x in blocked["BOUNDED_AUTO"])
    assert blocked["OBSERVE_ONLY"] == []  # an observer may arm without acknowledging (control.decide_arm)
    snap = doc["account"]["snapshot"]
    assert snap["cash"] is None and snap["usable_cash"] is None and snap["cash_basis"] == "UNKNOWN"


def test_unknown_is_none_never_zero(exports, tmp_path):
    (path, _), _ = exports["no_config"]
    doc = _load(path)
    assert doc["config_supplied"] is False
    assert doc["limits"] is None and doc["bounds"] is None and doc["grants"]["configured"] is None
    assert doc["account"]["snapshot"]["freshness_at_export"] == "UNKNOWN"
    (idle, _), _ = exports["idle"]
    assert _load(idle)["account"]["positions"] == []  # a COMPLETE read with no holdings: known empty
    # A journal with a boot and no account read: the account is unknown, not empty.
    journal = ExecutionJournal.open(tmp_path / "boot.execution.sqlite3")
    clock = h.Clock()
    adapter = h.VenueAdapter(clock)
    h.build(journal, adapter)
    doc = se.build_status(journal, h.SCOPE, now=clock())
    journal.close()
    assert doc["account"]["snapshot"] is None and doc["account"]["positions"] is None
    assert doc["account"]["external_orders"] is None
    assert doc["pnl"]["baseline_recorded"] is False and doc["pnl"]["realized_total"] is None
    assert doc["cycles"]["last"] is None and doc["control"]["reconciliation"] == "NOT_RUN"


def test_nothing_secret_or_replayable_is_exported(exports):
    (path, _), root = exports["populated"]
    text = path.read_text(encoding="utf-8")
    keys = {p.rsplit(".", 1)[-1].split("[")[0] for p, _ in _walk(_load(path))}
    assert not keys & {"approval_nonce", "nonce", "client_order_id", "request_digest", "payload_json", "grant_json",
                       "provider_order_id", "signature", "key", "secret", "credential"}
    with ExecutionJournal.open(root / "fixture.execution.sqlite3") as journal:
        attempts = [a for r in _load(path)["attempts"]["rows"] for a in journal.attempts_for(r["intent_key"])]
    assert attempts
    for a in attempts:
        for value in (a.approval_nonce, a.request_digest) + ((a.provider_order_id,) if a.provider_order_id else ()):
            assert value not in text
    assert "BEGIN" not in text


def test_free_text_is_redacted_and_paths_reduced(tmp_path):
    journal = ExecutionJournal.open(tmp_path / "r.execution.sqlite3")
    clock = h.Clock()
    orch, _ = h.build(journal, h.VenueAdapter(clock))
    orch.set_latch(ctl.LatchScope.MARKET, "KXHIGHNY-26OCT08-B70", "copied token=abcdefghijklmnop from /var/lib/x/y.log")
    doc = se.build_status(journal, h.SCOPE, now=clock())
    journal.close()
    (latch,) = doc["control"]["latches"]
    assert latch["reason"] == "copied token=REDACTED from y.log"
    se.render(doc)


KEYISH = "MC4CAQAwBQYDK2VwBCIEIGx0Zm9yZXZlcmFuZGV2ZXJhbmRldmVyYW5k"  # base64-shaped, label-safe, not a real key


def test_plain_fields_and_multiline_text_never_bypass_redaction(tmp_path):
    """Review M1: labels (operator_ref, issuer_ref, worker_id) and record text are redacted like free text, a header on
    its own line is caught, and a venue order id named in text is redacted."""
    journal = ExecutionJournal.open(tmp_path / "m1.execution.sqlite3")
    clock = h.Clock()
    orch, _ = h.build(journal, h.VenueAdapter(clock), worker_id=KEYISH[:40])
    orch.set_latch(ctl.LatchScope.MARKET, "KXHIGHNY-26OCT08-B70",
                   "pasted by mistake\nKALSHI-ACCESS-SIGNATURE: c2lnbmF0dXJlYnl0ZXM= and order_id=8f3a77c1")
    orch.disarm(KEYISH, "Authorization: Basic dXNlcjpwYXNzd29yZA==")
    doc = se.build_status(journal, h.SCOPE, now=clock(), config=h.config(worker_id=KEYISH[:40]))
    journal.close()
    text = se.render(doc)  # passes: everything was cleaned before the check
    for leaked in (KEYISH, KEYISH[:40], "c2lnbmF0dXJlYnl0ZXM", "dXNlcjpwYXNzd29yZA", "8f3a77c1"):
        assert leaked not in text, leaked
    assert doc["control"]["last_disarm"]["operator_ref"] == "REDACTED"
    assert doc["service"]["last_boot"]["worker_id"] == "REDACTED"
    (latch,) = doc["control"]["latches"]
    assert latch["reason"].startswith("pasted by mistake\nKALSHI-ACCESS-SIGNATURE=REDACTED")


@pytest.mark.parametrize("raw", [
    "line one\nkalshi-access-key: 0b5f0c33",  # hidden behind an escape once JSON-encoded
    "Authorization: Basic dXNlcjpwYXNzd29yZA==",
    "private_key=abcdefgh",
    f"body {KEYISH}",
    "venue order_id=8f3a77c1",
])
def test_render_checks_raw_strings_and_keys_before_encoding(exports, raw):
    (path, _), _ = exports["idle"]
    doc = _load(path)
    doc["control"]["log"].append(raw)
    with pytest.raises(se.ExportRefused):
        se.render(doc)
    doc = _load(path)
    doc["control"][raw] = "x"
    with pytest.raises(se.ExportRefused):
        se.render(doc)


@pytest.mark.parametrize("mutate,why", [
    (lambda d: d.update(schema="other/1"), "schema"),
    (lambda d: d.update(cash=1.5), "float"),
    (lambda d: d.update(note="-----BEGIN CERTIFICATE-----"), "secret"),
    (lambda d: d.update(note="Bearer abcdefghijklmnopqrstuvwxyz"), "secret"),
    (lambda d: d.update(blob="x" * (se.MAX_BYTES + 1)), "larger"),
    (lambda d: d.update(when=timedelta(seconds=1)), "timedelta"),
])
def test_render_refuses_what_must_never_be_written(exports, mutate, why):
    (path, _), _ = exports["idle"]
    doc = _load(path)
    mutate(doc)
    with pytest.raises(se.ExportRefused):
        se.render(doc)


def test_a_missing_journal_is_no_journal_and_is_not_created(tmp_path):
    target = tmp_path / "absent.execution.sqlite3"
    doc = se.status_for_path(target, h.SCOPE, now=h.T0)
    assert doc["journal"]["state"] == "NO_JOURNAL" and not target.exists()
    assert "control" not in doc and "account" not in doc  # nothing about an account that was never read
    se.render(doc)


@pytest.mark.parametrize("content", [b"not a database at all" * 10, b""])
def test_an_unreadable_journal_is_an_error_state_never_a_raise(tmp_path, content):
    target = tmp_path / "bad.execution.sqlite3"
    target.write_bytes(content)
    doc = se.status_for_path(target, h.SCOPE, now=h.T0)
    assert doc["journal"]["state"] == ("NO_JOURNAL" if not content else "ERROR")
    assert str(tmp_path) not in json.dumps(doc)
    se.render(doc)


def test_the_export_reads_only_and_is_deterministic(exports):
    (path, at), root = exports["populated"]
    with ExecutionJournal.open(root / "fixture.execution.sqlite3") as journal:
        before = journal.verify_chain()
        config = h.config()
        one = se.render(se.build_status(journal, h.SCOPE, now=at, config=config))
        two = se.render(se.build_status(journal, h.SCOPE, now=at, config=config))
        after = journal.verify_chain()
    assert one == two == path.read_text(encoding="utf-8")
    assert before.events == after.events and after.ok


def test_write_status_is_atomic_and_leaves_no_temporary_file(exports, tmp_path):
    (path, _), _ = exports["idle"]
    out = se.write_status(_load(path), tmp_path / se.FILENAME)
    assert out.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")
    assert [p.name for p in tmp_path.iterdir()] == [se.FILENAME]
    with pytest.raises(se.ExportRefused):
        se.write_status({"schema": "x"}, tmp_path / "other.json")
    assert not (tmp_path / "other.json").exists() and [p.name for p in tmp_path.iterdir()] == [se.FILENAME]


def test_a_config_for_another_scope_is_refused(tmp_path):
    journal = ExecutionJournal.open(tmp_path / "s.execution.sqlite3")
    other = h.m.AccountScope(h.m.Environment.FIXTURE, "another-acct")
    with pytest.raises(ValueError):
        se.build_status(journal, other, now=h.T0, config=h.config())
    journal.close()


def test_the_module_imports_no_capability_and_the_dashboard_reads_the_same_names():
    imports = set()
    for node in ast.walk(ast.parse(SRC.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
        elif isinstance(node, ast.Import):
            imports |= {a.name for a in node.names}
    assert not {m for m in imports if m.split(".")[-1] in ("transport", "signer", "fake_venue")}
    from edge_lab.dashboard import data as d

    assert d.EXECUTION_STATUS_FILE == se.FILENAME and d.EXECUTION_STATUS_SCHEMA == se.SCHEMA
    assert d.EXECUTION_STATUS_MAX_BYTES >= se.MAX_BYTES
    from edge_lab.dashboard.views import ops_common
    from edge_lab.execution.model import AUTHORIZED_ENVIRONMENTS

    # Review M2: the Terminal's own allowlist equals today's code authorization; changing one needs the other.
    assert set(ops_common.TERMINAL_ENVIRONMENTS) == {e.value for e in AUTHORIZED_ENVIRONMENTS} == {"FIXTURE"}


def test_every_export_matches_the_dashboard_shape(exports, tmp_path):
    """The dashboard's shape check accepts every projection the exporter writes (and nothing malformed)."""
    from edge_lab.dashboard import data as d

    for scenario, ((path, _), _) in exports.items():
        assert d.execution_shape_problems(_load(path)) == [], scenario
    doc = se.status_for_path(tmp_path / "absent.execution.sqlite3", h.SCOPE, now=h.T0)
    assert d.execution_shape_problems(json.loads(se.render(doc))) == []
