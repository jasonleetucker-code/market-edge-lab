"""Local read-only dashboard (owner directive 2026-09-23, priority 5).

Every test calls the WSGI app directly: no sockets, no network.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab import daily, exp001_shadow as shadow, exp001_stageb as stageb
from edge_lab.dashboard.app import host_allowed
from edge_lab.dashboard import Config, make_app, views
from edge_lab.dashboard import data as dd
from edge_lab.dashboard import server
from edge_lab.dashboard.demo import DEMO_PREFIX, build_demo
from edge_lab.shadow_ledger import ShadowLedger
from edge_lab.storage import SnapshotStore
from test_daily import _settled_run
from test_exp001_shadow import CLOSED, _result, _settled
from test_forward import D, _full_day

UTC = timezone.utc
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)  # after D's decision, fills and settlement (fixture: 09-30)
ROUTES = ["/", "/opportunities", "/positions", "/outcome-board", "/risk", "/experiments"]
BANNER = "SHADOW — NO REAL MONEY"
REPO = Path(__file__).resolve().parents[1]


def call(app, path="/", method="GET", query="", host="127.0.0.1:8765"):
    captured = {}

    def start_response(status, headers):
        captured["status"], captured["headers"] = status, dict(headers)

    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query}
    if host is not None:
        environ["HTTP_HOST"] = host
    body = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], body.decode("utf-8")


def config(**kw) -> Config:
    kw.setdefault("clock", lambda: NOW)
    return Config(**kw)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_status(directory: Path, *, generated: datetime = NOW - timedelta(hours=1), receipt: dict | None = None):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "latest.json").write_text(json.dumps({
        "generated_at_utc": generated.isoformat(), "last_closed_target_date": D.isoformat(),
        "last_closed_status": "VALID", "last_closed_reasons": [], "valid_days": 1, "first_valid_day": D.isoformat(),
        "days_with_captures": 1, "invalid_days": []}), encoding="utf-8")
    (directory / "shadow_daily.json").write_text(json.dumps(receipt if receipt is not None else {
        "schema": "edge-lab-shadow-daily-receipt/1", "generated_at_utc": generated.isoformat(),
        "code_version": "abc1234", "state": "HEALTHY_TRADED", "exit_code": 0,
        "days": [{"target_date": D.isoformat(), "capture_status": "VALID", "decision_time_utc": "2026-09-22T22:00:00Z",
                  "result": "TRADED", "accounts": {shadow.ACCOUNT_ID: {"decisions": 12, "fills": 3,
                                                                       "no_fills": {}}}, "problems": []}],
        "settlement": {"refresh": {"status": "ok", "events_requested": 1, "markets_stored": 12, "errors": []},
                       "settled": 3, "pending": []},
        "fee": {"schedule_id": "kalshi-quadratic-taker-v1", "status": "UNVERIFIED_CURRENT_SCHEDULE",
                "claimable": False},
        "problems": []}), encoding="utf-8")


@pytest.fixture(scope="module")
def model():
    return stageb.load_model()


@pytest.fixture
def populated(tmp_path, monkeypatch, model):
    """A real Stage B day through the real pipeline: capture, decisions, fills, settlement."""
    store = SnapshotStore(tmp_path / "evidence" / "edge_lab.sqlite3")
    ledger = ShadowLedger(tmp_path / "ledger" / "shadow_ledger.sqlite3")
    _full_day(store, monkeypatch)
    summary = shadow.run_day(store, ledger, D, model=model, now=CLOSED)
    assert summary["stage_b_day_status"] == "VALID" and summary["filled"] > 0
    _settled(store, 67, _result(67))
    shadow.settle_open_positions(store, ledger)
    store.start_run("health-run")
    store.record_source_health(run_id="health-run", source_id="kalshi_public", started_at_utc="2026-10-01T10:00:00Z",
                               completed_at_utc="2026-10-01T10:00:03Z", duration_ms=3000, status="ok", records=5)
    store.finish_run("health-run", status="succeeded")
    status_dir = tmp_path / "status"
    write_status(status_dir)
    cfg = config(db=store.path, ledger=ledger.path, status_dir=status_dir, experiments_root=REPO / "experiments")
    return cfg, store, ledger


# --------------------------------------------------------------------------- basics


def test_empty_state_every_route_is_explicit_no_data(tmp_path):
    app = make_app(config())
    for route in ROUTES:
        status, headers, body = call(app, route)
        assert status == "200 OK", route
        assert BANNER in body and 'name="viewport"' in body
        assert "NO DATA / NOT STARTED" in body, route
        assert "SYNTHETIC DEMO DATA" not in body
    _, _, overview = call(app, "/")
    main = overview.split("<main>")[1]
    assert "$" not in main, "an empty state must never show a balance (missing is not zero)"
    assert shadow.ACCOUNT_ID in main and dd.RESEARCH_ACCOUNT_ID in main


def test_configured_but_missing_sources_are_no_data_and_never_created(tmp_path):
    db, ledger, status = tmp_path / "no.sqlite3", tmp_path / "no_ledger.sqlite3", tmp_path / "nostatus"
    app = make_app(config(db=db, ledger=ledger, status_dir=status, experiments_root=tmp_path / "noexp"))
    for route in ROUTES:
        status_line, _, body = call(app, route)
        assert status_line == "200 OK" and "NO DATA / NOT STARTED" in body
    assert not db.exists() and not ledger.exists() and not status.exists()


def test_security_headers_on_every_response(tmp_path):
    app = make_app(config())
    for route in ROUTES + ["/healthz", "/missing"]:
        _, headers, _ = call(app, route)
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Cache-Control"] == "no-store"
        assert headers["Content-Security-Policy"].startswith("default-src 'none'; style-src 'unsafe-inline'")
    _, headers, _ = call(app, "/")
    assert headers["Content-Type"] == "text/html; charset=utf-8"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_only_get_and_head(method):
    status, headers, body = call(make_app(config()), "/", method=method)
    assert status.startswith("405") and headers["Allow"] == "GET, HEAD" and BANNER in body


def test_head_has_headers_but_no_body():
    status, headers, body = call(make_app(config()), "/", method="HEAD")
    assert status == "200 OK" and body == "" and int(headers["Content-Length"]) > 0


def test_unknown_route_is_404_and_escaped():
    status, _, body = call(make_app(config()), "/<script>x")
    assert status.startswith("404") and "<script>x" not in body and "&lt;script&gt;x" in body


def test_healthz_is_plain_ok_without_data():
    status, headers, body = call(make_app(config()), "/healthz")
    assert status == "200 OK" and body == "ok\n" and headers["Content-Type"].startswith("text/plain")


def test_query_strings_are_ignored(populated):
    cfg, _, _ = populated
    app = make_app(cfg)
    plain = call(app, "/risk")[2]
    assert call(app, "/risk", query="sql=DROP%20TABLE%20x&path=/etc/passwd")[2] == plain


def test_mobile_layout_rules():
    _, _, body = call(make_app(config()), "/")
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in body
    assert "@media (max-width:640px)" in body and ".scroll{overflow-x:auto" in body


def test_every_table_scrolls_inside_its_container(populated):
    cfg, _, _ = populated
    app = make_app(cfg)
    for route in ROUTES:
        body = call(app, route)[2]
        assert body.count("<table>") == body.count('<div class="scroll"><table>'), route


# --------------------------------------------------------------------------- populated


def test_populated_views_show_canonical_figures(populated):
    cfg, store, ledger = populated
    app = make_app(cfg)
    state = ledger.state(shadow.ACCOUNT_ID)
    assert state.settlements > 0

    overview = call(app, "/")[2]
    assert "cost-basis shadow equity (not liquidation value)" in overview
    assert "notional starting bankroll" in overview and f"${state.equity}" in overview
    assert f"${state.starting_bankroll}" in overview
    assert "HEALTHY_TRADED" in overview and "UNVERIFIED_CURRENT_SCHEDULE" in overview
    assert "OPERATIONAL" in overview and "RESEARCH (FROZEN EXP-001 RULE)" in overview
    research = ledger.state(dd.RESEARCH_ACCOUNT_ID)  # opened by run_day alongside the operational account
    assert f"${research.starting_bankroll}" in overview and research.fills == state.fills
    assert "NOT RECOMMENDED" in overview

    opps = call(app, "/opportunities")[2]
    decision = json.loads(ledger.entries(shadow.ACCOUNT_ID)[1]["payload_json"])
    assert decision["opportunity"]["model_probability"] in opps
    assert "12 decisions recorded" in opps and "REJECT" in opps and "QUALIFY" in opps

    positions = call(app, "/positions")[2]
    assert "Accounting basis" in positions and "FILLED" in positions
    assert f"${state.realized_pnl}".replace("$-", "-$") in positions

    board = call(app, "/outcome-board")[2]
    assert "upper bound, not a predicted scenario" in board and "settled" in board

    risk_page = call(app, "/risk")[2]
    assert shadow.RISK_POLICY.policy_id in risk_page and "NOT RECOMMENDED" in risk_page
    assert "remaining risk capacity" in risk_page and "never counted as cash" in risk_page
    assert "binding constraint" in risk_page

    exps = call(app, "/experiments")[2]
    assert "EXP-001" in exps and "PASS" in exps and "kalshi_public" in exps
    assert "kalshi-quadratic-taker-v1" in exps and "REPORT.md" in exps


def test_rendering_never_writes_to_the_stores(populated):
    cfg, store, ledger = populated
    watched = [p for p in (store.path, Path(f"{store.path}-wal"), ledger.path) if p.exists()]
    before = {p: sha(p) for p in watched}
    ledger_dir = sorted(p.name for p in ledger.path.parent.iterdir())
    app = make_app(cfg)
    for _ in range(2):
        for route in ROUTES + ["/healthz"]:
            assert call(app, route)[0] == "200 OK"
    assert {p: sha(p) for p in watched} == before
    assert sorted(p.name for p in ledger.path.parent.iterdir()) == ledger_dir


def test_stale_status_files_are_flagged(tmp_path):
    status_dir = tmp_path / "status"
    write_status(status_dir, generated=NOW - timedelta(hours=30))
    body = call(make_app(config(status_dir=status_dir)), "/")[2]
    assert "STALE" in body and "collector status file is STALE" in body and "pipeline receipt is STALE" in body


def test_fresh_status_file_is_not_flagged(tmp_path):
    status_dir = tmp_path / "status"
    write_status(status_dir, generated=NOW - timedelta(hours=2))
    body = call(make_app(config(status_dir=status_dir)), "/")[2]
    assert "FRESH" in body and "is STALE" not in body


def test_corrupted_status_json_is_an_error_panel_without_paths(tmp_path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    (status_dir / "latest.json").write_text("{not json", encoding="utf-8")
    (status_dir / "shadow_daily.json").write_text("[1, 2]", encoding="utf-8")
    app = make_app(config(status_dir=status_dir))
    body = call(app, "/")[2]
    assert "ERROR" in body and "latest.json cannot be read" in body and "shadow_daily.json is not a JSON object" in body
    assert str(tmp_path) not in body and "Traceback" not in body
    assert call(app, "/experiments")[0] == "200 OK"


def test_receipt_fields_are_all_optional(tmp_path):
    status_dir = tmp_path / "status"
    write_status(status_dir, receipt={"state": "FAILED"})
    app = make_app(config(status_dir=status_dir))
    for route in ROUTES:
        assert call(app, route)[0] == "200 OK"
    body = call(app, "/")[2]
    assert "FAILED" in body and "pipeline receipt state is FAILED" in body


def test_unreadable_ledger_is_an_error_panel(tmp_path):
    bad = tmp_path / "private" / "shadow_ledger.sqlite3"
    bad.parent.mkdir()
    bad.write_bytes(b"this is not a sqlite database at all" * 20)
    body = call(make_app(config(ledger=bad)), "/positions")[2]
    assert "ERROR" in body and str(tmp_path) not in body and "Traceback" not in body


def test_ledger_activity_after_clock_is_an_error_not_a_report(populated):
    cfg, _, _ = populated
    early = Config(db=cfg.db, ledger=cfg.ledger, status_dir=cfg.status_dir, clock=lambda: CLOSED - timedelta(days=1))
    body = call(make_app(early), "/risk")[2]
    assert "ERROR" in body and "precedes ledger activity" in body


def test_view_crash_is_a_500_without_traceback(monkeypatch, tmp_path):
    def boom(ctx):
        raise RuntimeError(f"failed reading {tmp_path}/secret/file.sqlite3")
    monkeypatch.setitem(views.PAGES, "/risk", ("Risk & capital", boom))
    status, _, body = call(make_app(config()), "/risk")
    assert status.startswith("500") and BANNER in body and str(tmp_path) not in body and "Traceback" not in body


def test_short_error_strips_directories():
    cfg = Config(ledger=Path("/srv/private/data/ledger.sqlite3"))
    msg = dd.short_error(RuntimeError("shadow ledger /srv/private/data/ledger.sqlite3 is missing; see /etc/x/y"), cfg)
    assert "/srv" not in msg and "/etc" not in msg and "ledger.sqlite3" in msg and msg.startswith("RuntimeError")


# --------------------------------------------------------------------------- escaping


def test_untrusted_ledger_and_receipt_content_is_escaped(tmp_path):
    evil = "<script>alert(1)</script>"
    ledger = ShadowLedger(tmp_path / "ledger.sqlite3")
    shadow.ensure_account(ledger)
    ledger.record_decision(shadow.ACCOUNT_ID, {
        "decision_id": "dec-x", "slot": f"2026-09-23|kalshi:{evil}|YES", "opportunity_id": "x",
        "as_of_utc": "2026-09-22T22:00:00+00:00", "qualification": "REJECT", "reason": evil, "reasons": [evil],
        "market_id": f"kalshi:{evil}", "side": "YES", "event_id": "e", "outcome_cluster": evil,
        "opportunity": {"model_probability": evil, "executable_price": evil}, "sizing": None, "claimable": False})
    status_dir = tmp_path / "status"
    write_status(status_dir, receipt={"state": evil, "problems": [evil], "days": [{"target_date": evil,
                                                                                    "problems": [evil]}]})
    app = make_app(config(ledger=ledger.path, status_dir=status_dir))
    for route in ROUTES:
        body = call(app, route)[2]
        assert "<script" not in body, route
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in call(app, "/opportunities")[2]


# --------------------------------------------------------------------------- binding


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "::1", "[::1]", "localhost", "LOCALHOST"])
def test_loopback_hosts_are_allowed(host):
    assert server.is_loopback(host) and server.check_bind_host(host, False) is None


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "10.0.0.1", "203.0.113.5", "example.com", ""])
def test_non_loopback_hosts_are_refused_without_override(host):
    assert not server.is_loopback(host)
    with pytest.raises(server.NonLoopbackRefused):
        server.check_bind_host(host, False)
    warning = server.check_bind_host(host, True)
    assert warning and "NOT authorized" in warning


def test_main_refuses_non_loopback_before_binding(monkeypatch, capsys):
    def no_bind(*a, **k):
        raise AssertionError("must not bind")
    monkeypatch.setattr(server, "make_server", no_bind)
    assert server.main(["--host", "0.0.0.0"]) == 2
    assert "refusing to bind" in capsys.readouterr().err


def test_main_warns_and_serves_with_override(monkeypatch, capsys):
    served = {}

    class FakeServer:
        server_port = 8765

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            served["closed"] = True

    def fake_make_server(host, port, app, **kw):
        served.update(host=host, port=port)
        return FakeServer()
    monkeypatch.setattr(server, "make_server", fake_make_server)
    assert server.main(["--host", "0.0.0.0", "--allow-non-loopback", "--port", "9999"]) == 0
    assert served == {"host": "0.0.0.0", "port": 9999, "closed": True}
    assert "WARNING" in capsys.readouterr().err


def test_default_bind_is_loopback():
    args = server.build_parser().parse_args([])
    assert args.host == "127.0.0.1" and args.port == 8765


# --------------------------------------------------------------------------- demo


def test_demo_is_isolated_from_configured_paths(tmp_path):
    real_ledger = ShadowLedger(tmp_path / "real" / "shadow_ledger.sqlite3")
    shadow.ensure_account(real_ledger)
    before = sha(real_ledger.path)
    missing_db = tmp_path / "real" / "edge_lab.sqlite3"
    real_status = tmp_path / "real" / "status"
    args = server.build_parser().parse_args(["--demo", "--ledger", str(real_ledger.path), "--db", str(missing_db),
                                             "--status-dir", str(real_status)])
    cfg, root = server.config_from_args(args)
    try:
        assert cfg.demo and root.name.startswith(DEMO_PREFIX)
        for p in (cfg.db, cfg.ledger, cfg.status_dir):
            assert root in p.parents and tmp_path not in p.parents
        app = make_app(cfg)
        for route in ROUTES:
            status, _, body = call(app, route)
            assert status == "200 OK" and "SYNTHETIC DEMO DATA" in body and BANNER in body
        overview = call(app, "/")[2]
        assert "RESEARCH (FROZEN EXP-001 RULE)" in overview and "PENDING_SETTLEMENT" in overview
        demo_ledger = ShadowLedger.open_readonly(cfg.ledger)
        assert set(demo_ledger.accounts()) == {dd.OPERATIONAL_ACCOUNT_ID, dd.RESEARCH_ACCOUNT_ID}
        assert all(p.market_id.startswith("kalshi:DEMO-")
                   for p in demo_ledger.state(dd.OPERATIONAL_ACCOUNT_ID).positions)
    finally:
        shutil.rmtree(root)
    assert sha(real_ledger.path) == before
    assert not missing_db.exists() and not real_status.exists()
    assert real_ledger.state(shadow.ACCOUNT_ID).decisions == 0


def test_demo_builds_fresh_directory_each_time():
    a, root_a = build_demo()
    b, root_b = build_demo()
    try:
        assert root_a != root_b and a.ledger != b.ledger
    finally:
        shutil.rmtree(root_a)
        shutil.rmtree(root_b)


def test_non_demo_pages_have_no_watermark(populated):
    cfg, _, _ = populated
    assert "SYNTHETIC DEMO DATA" not in call(make_app(cfg), "/")[2]


def test_fee_blocker_follows_the_canonical_schedule():
    cfg = config()
    body = call(make_app(cfg), "/")[2]
    state = dd.fee_state(NOW)
    if not state.claimable:
        assert f"is {state.status.value}: claimable = false" in body
    elif state.claim_basis.value == "CONSERVATIVE_BOUND":
        assert "claim basis CONSERVATIVE_BOUND" in body and "lower bound" in body
        assert f"{state.rounding_allowance_per_contract} USD per contract" in body
    else:
        assert state.claim_basis.value == "EXACT" and "claimable = false" not in body


def test_fee_blocker_before_the_verification_record_says_unverified():
    before = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    body = call(make_app(config(clock=lambda: before)), "/")[2]
    assert "is UNVERIFIED_CURRENT_SCHEDULE: claimable = false" in body


def test_fee_page_shows_each_verification_component():
    body = call(make_app(config()), "/experiments")[2]
    for component in ("COEFFICIENT", "SERIES_MULTIPLIER", "SCHEDULED_CHANGES", "ROUNDING_FOR_ACCOUNT_TYPE",
                      "ACCOUNT_TYPE", "MAKER_FEES", "OWNER_ATTESTED"):
        assert component in body


def test_no_demo_money_in_real_render(populated):
    cfg, _, ledger = populated
    body = call(make_app(cfg), "/positions")[2]
    assert "DEMO-" not in body
    assert re.search(r"kalshi:KXHIGHNY-26SEP23-", body)
    assert Decimal(ledger.state(shadow.ACCOUNT_ID).starting_bankroll) == shadow.STARTING_BANKROLL


def test_cli_delegates_to_the_dashboard(monkeypatch):
    import edge_lab.dashboard as dash
    from edge_lab import cli

    seen = {}
    monkeypatch.setattr(dash, "main", lambda argv: seen.setdefault("argv", argv) and 0)
    assert cli.main(["dashboard", "--host", "0.0.0.0"]) == 0
    assert seen["argv"] == ["--host", "0.0.0.0"]


# --------------------------------------------------------------------------- review fixes (PR #28)


@pytest.mark.parametrize("host", ["127.0.0.1:8765", "127.0.0.1", "localhost:8765", "LOCALHOST", "[::1]:8765",
                                  "[::1]", "127.0.0.2:8765", "localhost.", None])
def test_local_host_headers_are_served(host):
    assert host_allowed(host)
    assert call(make_app(config()), "/", host=host)[0] == "200 OK"


@pytest.mark.parametrize("host", ["evil.example.com", "evil.example.com:8765", "127.0.0.1.evil.example.com",
                                  "localhost.evil.example.com:8765", "192.168.1.10:8765", "", "[::1",
                                  "[::1]evil.example.com", "localhost:evil", ":8765", "localhost:99999999"])
def test_foreign_host_headers_are_refused_dns_rebinding(host, populated):
    cfg, _, _ = populated
    app = make_app(cfg)
    for route in ROUTES + ["/healthz"]:
        status, headers, body = call(app, route, host=host)
        assert status.startswith("400"), (host, route)
        assert "EXP-001" not in body and "kalshi:" not in body and headers["Cache-Control"] == "no-store"


def test_approved_bind_host_is_accepted_only_when_configured():
    assert call(make_app(config()), "/", host="10.0.0.5:8765")[0].startswith("400")
    assert call(make_app(config(allowed_hosts=("10.0.0.5",))), "/", host="10.0.0.5:8765")[0] == "200 OK"


def test_main_passes_the_approved_host_to_the_app(monkeypatch):
    seen = {}

    class FakeServer:
        server_port = 8765

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    def fake_make_server(host, port, app, **kw):
        seen["app"], seen["server_class"] = app, kw["server_class"]
        return FakeServer()
    monkeypatch.setattr(server, "make_server", fake_make_server)
    assert server.main(["--host", "10.0.0.5", "--allow-non-loopback"]) == 0
    assert call(seen["app"], "/healthz", host="10.0.0.5:8765")[0] == "200 OK"
    assert call(seen["app"], "/healthz", host="evil.example.com")[0].startswith("400")
    assert seen["server_class"] is not server.server_class_for("::1")


def _serve_main(monkeypatch, argv):
    seen = {}

    class FakeServer:
        server_port = 8765

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    def fake_make_server(host, port, app, **kw):
        seen.update(host=host, app=app)
        return FakeServer()
    monkeypatch.setattr(server, "make_server", fake_make_server)
    return server.main(argv), seen


TS_NAME = "vmi1.tailabc123.ts.net"


def test_tailscale_serve_host_is_accepted_exactly_and_bind_stays_loopback(monkeypatch):
    code, seen = _serve_main(monkeypatch, ["--tailscale-serve-host", "VMI1.tailabc123.ts.net."])
    assert code == 0 and seen["host"] == "127.0.0.1"
    app = seen["app"]
    for host in (TS_NAME, TS_NAME + ":443", TS_NAME.upper(), TS_NAME + ".", "127.0.0.1:8765", "localhost"):
        assert call(app, "/", host=host)[0] == "200 OK", host
    for host in ("other.tailabc123.ts.net", "vmi1.tailother.ts.net", "evil.vmi1.tailabc123.ts.net",
                 "vmi1.tailabc123.ts.net.evil.example.com", "tailabc123.ts.net", "ts.net", "evil.example.com",
                 "100.107.60.6", "0.0.0.0", "192.168.1.10:8765", TS_NAME + ":evil"):
        assert call(app, "/", host=host)[0].startswith("400"), host


@pytest.mark.parametrize("name", ["", "ts.net", "tailabc123.ts.net", "*.tailabc123.ts.net", "a.b.c.ts.net",
                                  "vmi1.tailabc123.ts.net:443", "vmi1.tailabc123.example.com", "localhost",
                                  "100.107.60.6", "-vmi1.tailabc123.ts.net", "vmi1.tailabc123.ts.net/x",
                                  "vmi1..ts.net", "vmi 1.tailabc123.ts.net"])
def test_tailscale_serve_host_must_be_one_exact_magicdns_name(monkeypatch, capsys, name):
    def no_bind(*a, **k):
        raise AssertionError("must not bind")
    monkeypatch.setattr(server, "make_server", no_bind)
    assert server.main([f"--tailscale-serve-host={name}"]) == 2
    assert "not a Tailscale MagicDNS name" in capsys.readouterr().err


def test_tailscale_serve_host_refuses_a_non_loopback_bind(monkeypatch, capsys):
    def no_bind(*a, **k):
        raise AssertionError("must not bind")
    monkeypatch.setattr(server, "make_server", no_bind)
    assert server.main(["--host", "0.0.0.0", "--allow-non-loopback", "--tailscale-serve-host", TS_NAME]) == 2
    assert "needs a loopback --host" in capsys.readouterr().err


def test_without_the_flag_a_tailnet_host_is_refused(monkeypatch):
    code, seen = _serve_main(monkeypatch, [])
    assert code == 0 and call(seen["app"], "/", host=TS_NAME)[0].startswith("400")


def test_ipv6_loopback_uses_an_ipv6_socket_and_bind_errors_are_one_line(monkeypatch, capsys):
    seen = {}

    def fake_make_server(host, port, app, **kw):
        seen.update(host=host, server_class=kw["server_class"])
        raise OSError(98, "Address already in use")
    monkeypatch.setattr(server, "make_server", fake_make_server)
    assert server.main(["--host", "[::1]"]) == 2
    assert seen["host"] == "::1" and seen["server_class"].address_family == server.socket.AF_INET6
    err = capsys.readouterr().err
    assert "cannot bind" in err and "Traceback" not in err


def test_sigterm_removes_the_demo_directory_and_restores_the_handler(monkeypatch):
    import signal
    before = signal.getsignal(signal.SIGTERM)
    seen = {}

    class FakeServer:
        server_port = 8765

        def serve_forever(self):
            signal.raise_signal(signal.SIGTERM)

        def server_close(self):
            pass

    real_config_from_args = server.config_from_args

    def spy(args):
        cfg, root = real_config_from_args(args)
        seen["root"] = root
        return cfg, root
    monkeypatch.setattr(server, "config_from_args", spy)
    monkeypatch.setattr(server, "make_server", lambda *a, **k: FakeServer())
    assert server.main(["--demo"]) == 0
    assert seen["root"] is not None and not seen["root"].exists()
    assert signal.getsignal(signal.SIGTERM) == before


@pytest.fixture
def real_receipt(tmp_path, monkeypatch, model):
    """A receipt written by the real daily pipeline over contradicting settlement evidence."""
    store = SnapshotStore(tmp_path / "evidence" / "edge_lab.sqlite3")
    ledger_path = tmp_path / "ledger" / "shadow_ledger.sqlite3"
    status_dir = tmp_path / "status"
    _full_day(store, monkeypatch)
    _settled_run(store, 67, _result(67), "first", received="2026-09-23T12:00:00+00:00")
    daily.run(store.path, ledger_path, status_dir=status_dir, model=model,
              now=datetime(2026, 9, 23, 20, tzinfo=UTC))
    _settled_run(store, 70, _result(70), "later", received="2026-09-23T13:00:00+00:00")
    now = datetime(2026, 9, 24, 16, tzinfo=UTC)  # D+1's window closed with no capture: a missed day
    receipt, code = daily.run(store.path, ledger_path, status_dir=status_dir, model=model, now=now)
    assert (receipt["state"], code) == ("INVALID_CAPTURE", 3) and receipt["settlement"]["conflicts"]
    cfg = config(db=store.path, ledger=ledger_path, status_dir=status_dir, clock=lambda: now + timedelta(minutes=5))
    return cfg, receipt


def test_real_pipeline_receipt_is_fully_rendered(real_receipt):
    cfg, receipt = real_receipt
    app = make_app(cfg)
    overview = call(app, "/")[2]
    conflict = receipt["settlement"]["conflicts"][0]
    assert 'class="tag err">INVALID_CAPTURE' in overview
    assert 'class="tag err">MISSING_CAPTURE' in overview and "2026-09-24" in overview
    assert "SETTLEMENT_CONFLICT" in overview and conflict["position_id"] in overview
    assert "closed day(s) with no capture" in overview and "latest day 2026-09-24 is INVALID_CAPTURE" in overview
    assert receipt["settlement"]["evidence_cutoff_utc"] in overview
    assert f"{receipt['valid_days']} / {receipt['closed_capture_days']}" in overview
    positions = call(app, "/positions")[2]
    assert "Settlement evidence conflicts reported by the latest receipt" in positions
    assert conflict["position_id"] in positions and "none recorded" not in positions.split("conflicts reported")[1][:400]
    experiments = call(app, "/experiments")[2]
    assert "risk vetoes" in experiments and "qualified" in experiments and conflict["position_id"] in experiments
    for route in ROUTES:
        assert call(app, route)[0] == "200 OK"


def test_demo_receipt_has_every_field_the_real_pipeline_writes(real_receipt):
    _, real = real_receipt
    cfg, root = build_demo()
    try:
        demo = json.loads((cfg.status_dir / dd.RECEIPT_FILE).read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(root)
    assert set(real) - {"repeat_of_previous_alert"} <= set(demo)
    assert set(real["settlement"]) <= set(demo["settlement"])
    assert set(real["days"][0]) <= set(demo["days"][0])
    real_acct = next(iter(real["days"][0]["accounts"].values()))
    assert set(real_acct) <= set(next(iter(demo["days"][0]["accounts"].values())))
    assert set(real["latest_day"]) <= set(demo["latest_day"])


@pytest.mark.parametrize("state,kind", [
    ("SETTLEMENT_CONFLICT", "err"), ("MISSING_CAPTURE", "err"), ("RESEARCH_INVALID_CASH", "err"),
    ("HALTED", "err"), ("NO_CAPTURE", "warn"), ("RISK_VETO", "warn"), ("INVALID_CAPTURE", "err"),
    ("HEALTHY_NO_SIGNAL", "ok"), ("something-new", "nd")])
def test_serious_states_are_not_neutral(state, kind):
    from edge_lab.dashboard.html import state_tag
    assert f'class="tag {kind}"' in state_tag(state)


def test_zero_capacity_is_halted_not_breach_and_is_a_blocker(populated, monkeypatch):
    import dataclasses
    real_assess = dd.risk.assess

    def exhausted(state, policy, as_of):
        rep = real_assess(state, policy, as_of)
        assert not rep.breaches
        return dataclasses.replace(rep, new_risk_allowed=False, remaining_risk_capacity=Decimal("0"))
    monkeypatch.setattr(dd.risk, "assess", exhausted)
    cfg, _, _ = populated
    app = make_app(cfg)
    overview = call(app, "/")[2]
    assert 'class="tag err">HALTED' in overview and "remaining risk capacity is zero" in overview
    assert "BREACH" not in overview
    assert f"{shadow.ACCOUNT_ID}: remaining risk capacity is zero; new risk halted" in overview
    assert 'class="tag err">HALTED' in call(app, "/risk")[2]


def test_research_invalid_cash_is_a_blocker(tmp_path):
    from edge_lab.dashboard.demo import _decision, _fill
    ledger = ShadowLedger(tmp_path / "ledger.sqlite3")
    shadow.ensure_account(ledger, shadow.RESEARCH)
    at = NOW - timedelta(days=1)
    dec = _decision(shadow.RESEARCH_ACCOUNT_ID, 1, at, "kalshi:X-B67.5", "YES", True, "QUALIFY", "0.41", "0.34",
                    "0.0158", "0.36", "0.05")
    ledger.record_decision(shadow.RESEARCH_ACCOUNT_ID, dec)
    ledger.record_fill(shadow.RESEARCH_ACCOUNT_ID, _fill(dec, False, "0", "0", "0", at + timedelta(days=1),
                                                          reason="RESEARCH_INVALID_CASH"))
    app = make_app(config(ledger=ledger.path))
    overview = call(app, "/")[2]
    assert "1 RESEARCH_INVALID_CASH no-fill(s)" in overview and "deviated from the frozen EXP-001 rule" in overview
    assert 'class="tag err">RESEARCH_INVALID_CASH' in call(app, "/positions")[2]


def test_demo_research_account_matches_the_real_research_account():
    cfg, root = build_demo()
    try:
        ledger = ShadowLedger.open_readonly(cfg.ledger)
        research = ledger.state(shadow.RESEARCH_ACCOUNT_ID)
        operational = ledger.state(shadow.ACCOUNT_ID)
        assert research.starting_bankroll == shadow.RESEARCH_BANKROLL
        assert operational.starting_bankroll == shadow.STARTING_BANKROLL
        risk_page = call(make_app(cfg), "/risk")[2]
        assert shadow.RESEARCH_SIZING_ID in risk_page and "Frozen EXP-001 rule" in risk_page
    finally:
        shutil.rmtree(root)


def test_withdrawal_amounts_are_labelled_not_available(populated):
    cfg, _, _ = populated
    body = call(make_app(cfg), "/risk")[2]
    assert "simulated arithmetic only; NOT available, NOT recommended" in body


def test_malformed_receipt_lists_are_malformed_not_none(tmp_path):
    status_dir = tmp_path / "status"
    write_status(status_dir, receipt={"state": "INVALID_CAPTURE", "missing_capture_days": "2026-09-01",
                                      "settlement": {"conflicts": {"a": 1}, "pending": "x"}})
    body = call(make_app(config(status_dir=status_dir)), "/")[2]
    assert body.count("MALFORMED (expected a list)") == 2
    for key in ("pending", "conflicts", "missing_capture_days"):
        assert f"pipeline receipt field {key} is MALFORMED" in body


def test_no_fill_counts_by_reason_are_readable(tmp_path):
    status_dir = tmp_path / "status"
    write_status(status_dir, receipt={"state": "HEALTHY_NO_SIGNAL", "days": [{"target_date": "2026-09-24",
        "accounts": {shadow.ACCOUNT_ID: {"decisions": 3, "qualified": 2, "fills": 1,
                                         "no_fills": {"RISK_VETO": 1}, "risk_vetoes": 1}}}]})
    body = call(make_app(config(status_dir=status_dir)), "/experiments")[2]
    assert "1 (RISK_VETO 1) no-fills" in body and "{" not in body.split("RISK_VETO 1")[0][-20:]


def test_c_level_previous_sigterm_handler_falls_back_to_default(monkeypatch):
    import signal
    calls = []
    real = signal.signal

    def fake_signal(sig, handler):
        calls.append(handler)
        return None if len(calls) == 1 else real(sig, signal.getsignal(sig))  # "installed from C"
    monkeypatch.setattr(server.signal, "signal", fake_signal)

    class FakeServer:
        server_port = 8765

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass
    monkeypatch.setattr(server, "make_server", lambda *a, **k: FakeServer())
    assert server.main([]) == 0
    assert calls == [server._sigterm_to_interrupt, signal.SIG_DFL]


def test_demo_filled_starter_fills_are_eligible():
    """The demo never shows a state real code cannot produce: a FILLED fill with an ineligible verdict."""
    cfg, root = build_demo()
    try:
        ledger = ShadowLedger.open_readonly(cfg.ledger)
        fills = [json.loads(r["payload_json"]) for a in ledger.accounts() for r in ledger.entries(a) if r["kind"] == "fill"]
    finally:
        shutil.rmtree(root)
    checked = [f for f in fills if f["status"] == "FILLED" and "starter_policy" in f]
    assert checked and all(f["starter_policy"]["eligible"] for f in checked)
    assert any(f["reason"] == "STARTER_POLICY_INELIGIBLE" for f in fills)
