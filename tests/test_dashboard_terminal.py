"""Market Edge Terminal v1 contract checks (docs/design/UI_CONTRACT.md).

These tests catch contract violations mechanically: assets, security, query validation,
formatting, state vocabulary, account scope and the token rules. They cannot certify that the
design looks right; reviewed screenshots do that (tests/browser/capture.py).
"""

from __future__ import annotations

import dataclasses
import fnmatch
import re
import shutil
import sys
import tomllib
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab import exp001_shadow as shadow
from edge_lab.dashboard import Config, make_app
from edge_lab.dashboard import components as c
from edge_lab.dashboard import html as h
from edge_lab.dashboard import presentation as pr
from edge_lab.dashboard.demo import build_demo
from edge_lab.shadow_ledger import ShadowLedger

REPO = Path(__file__).resolve().parents[1]
DASH = REPO / "src" / "edge_lab" / "dashboard"
STATIC = DASH / "static"
sys.path.insert(0, str(REPO / "tests" / "browser"))
from fixture_states import early  # noqa: E402

ROUTES = ["/", "/opportunities", "/positions", "/outcome-board", "/risk", "/experiments", "/alerts", "/more"]
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def call(app, path="/", method="GET", host="127.0.0.1:8765"):
    captured = {}
    query = ""
    if "?" in path:
        path, query = path.split("?", 1)

    def start_response(status, headers):
        captured["status"], captured["headers"] = status, dict(headers)
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "HTTP_HOST": host}
    body = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], body


@pytest.fixture(scope="module")
def demo():
    cfg, root = build_demo(experiments_root=REPO / "experiments")
    frozen = datetime.now(timezone.utc)
    cfg = dataclasses.replace(cfg, clock=lambda: frozen)  # identical renders are byte-identical
    yield make_app(cfg), cfg
    shutil.rmtree(root)


@pytest.fixture
def early_app(tmp_path):
    cfg, _ = early(tmp_path)
    return make_app(cfg)


def text(body: bytes) -> str:
    return body.decode("utf-8")


# --------------------------------------------------------------------------- static assets


def test_every_allowlisted_asset_is_served_immutable_with_its_type():
    app = make_app(Config(clock=lambda: NOW))
    ver = h.asset_version()
    for name, ctype in h.STATIC_FILES.items():
        status, headers, body = call(app, f"/static/{ver}/{name}")
        assert status == "200 OK", name
        assert headers["Content-Type"] == ctype and body == h.static_bytes(name)
        assert headers["Cache-Control"] == "public, max-age=31536000, immutable"
        assert headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("path", [
    "/static/{v}/../data.py", "/static/{v}/presentation.py", "/static/{v}/fonts/../../app.py",
    "/static/{v}/%2e%2e/app.py", "/static/{v}/ASSETS_PROVENANCE.md", "/static/{v}/icons.svg", "/static/000000000000/tokens.css",
    "/static/tokens.css", "/static/{v}/", "/static/{v}/TOKENS.CSS", "/static/{v}/fonts/", "/static/{v}/.gitattributes",
])
def test_unknown_or_traversing_static_paths_are_404_without_content(path):
    status, headers, body = call(make_app(Config(clock=lambda: NOW)), path.format(v=h.asset_version()))
    assert status.startswith("404") and headers["Cache-Control"] == "no-store" and len(body) < 64


def test_static_assets_still_need_a_local_host():
    status, _, _ = call(make_app(Config()), f"/static/{h.asset_version()}/tokens.css", host="evil.example.com")
    assert status.startswith("400")


def test_package_data_covers_every_served_asset():
    patterns = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"][
        "package-data"]["edge_lab.dashboard"]
    for name in [*h.STATIC_FILES, h.SPRITE_FILE, "fonts/LICENSE-IBM-Plex-OFL.txt", "LICENSE-Lucide.txt"]:
        assert any(fnmatch.fnmatch(f"static/{name}", p) for p in patterns), name
        assert (STATIC / name).is_file(), name


def test_asset_budgets():
    css = sum((STATIC / n).stat().st_size for n in ("tokens.css", "terminal.css"))
    js = (STATIC / "terminal.js").stat().st_size
    fonts = sum((STATIC / n).stat().st_size for n in h.STATIC_FILES if n.endswith(".woff2"))
    assert css <= 70 * 1024 and js <= 35 * 1024 and fonts <= 300 * 1024, (css, js, fonts)
    for name in h.STATIC_FILES:
        if name.endswith(".woff2"):
            assert (STATIC / name).read_bytes()[:4] == b"wOF2", name


def test_licenses_and_provenance_travel_with_the_assets():
    prov = (STATIC / "ASSETS_PROVENANCE.md").read_text(encoding="utf-8")
    assert "SIL Open Font License" in (STATIC / "fonts" / "LICENSE-IBM-Plex-OFL.txt").read_text(encoding="utf-8")
    assert "ISC" in (STATIC / "LICENSE-Lucide.txt").read_text(encoding="utf-8")
    import hashlib
    for name in [n for n in h.STATIC_FILES if n.endswith(".woff2")] + ["icons.svg"]:
        digest = hashlib.sha256((STATIC / name).read_bytes()).hexdigest()
        assert digest in prov, f"{name} hash not recorded in ASSETS_PROVENANCE.md"


# --------------------------------------------------------------------------- design-token rules

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def test_colours_and_fonts_are_defined_only_in_tokens_css():
    tokens = (STATIC / "tokens.css").read_text(encoding="utf-8")
    for token in ("--me-canvas: #101214", "--me-accent: #FF7A45", "--me-focus: #B8D6FF", "color-scheme: dark",
                  "--me-radius-panel: 6px", "--me-radius-control: 4px"):
        assert token in tokens
    css = (STATIC / "terminal.css").read_text(encoding="utf-8")
    assert not HEX.findall(css), "terminal.css must use tokens, not hex colours"
    assert not re.findall(r"font-family:(?!\s*var\()", css), "fonts come from tokens only"
    assert not re.findall(r"font:[^;]*[\"']", css), "font shorthands use token families only"
    for banned in ("gradient", "backdrop-filter", "blur(", "opacity:", "prefers-color-scheme", "overflow-x: hidden",
                   "box-shadow: 0"):
        assert banned not in css, banned


def test_page_modules_have_no_inline_styles_colours_or_scripts():
    for path in [*DASH.glob("*.py"), *(DASH / "views").glob("*.py")]:
        source = path.read_text(encoding="utf-8")
        assert "style=" not in source.replace('rel="stylesheet"', ""), path.name
        assert "<style" not in source and "<script>" not in source, path.name
        if path.name not in ("html.py",):  # the theme-color meta repeats --me-canvas
            assert not HEX.findall(source.replace("#i-", "")), path.name
        assert not re.search(r"\son[a-z]+=", source), path.name


def test_rendered_pages_have_no_inline_style_script_or_handlers(demo):
    app, _ = demo
    for route in ROUTES + ["/gallery", "/market?venue=kalshi&id=DEMO-B67.5&side=YES"]:
        body = text(call(app, route)[2])
        assert "<style" not in body and ' style="' not in body, route
        assert re.findall(r"<script[^>]*>", body) == [f'<script src="{h.asset_url("terminal.js")}" defer>'], route
        assert not re.search(r"<[^>]+\son[a-z]+=", body), route


# --------------------------------------------------------------------------- shell


def test_shell_has_mode_notice_wordmark_nav_and_bell(early_app):
    for route in ROUTES:
        body = text(call(early_app, route)[2])
        assert "MARKET EDGE" in body and "SHADOW · NO REAL MONEY" in body, route
        assert 'aria-label="Primary"' in body and 'aria-label="Primary (mobile)"' in body
        for label in ("Terminal", "Markets", "Portfolio", "Outcomes", "Risk", "Research &amp; Data", "Alerts", "More"):
            assert f"<span>{label}</span>" in body, (route, label)
        assert 'href="/alerts" aria-label="Alerts' in body
        assert body.count('aria-current="page"') >= 1
        assert "SYNTHETIC UI DEMO" not in body


def test_demo_carries_the_synthetic_strip_and_gallery_is_demo_only(demo, early_app):
    app, _ = demo
    assert "SYNTHETIC UI DEMO" in text(call(app, "/")[2])
    status, _, body = call(app, "/gallery")
    assert status == "200 OK" and "SYNTHETIC FIXTURES" in text(body)
    assert call(early_app, "/gallery")[0].startswith("404")
    assert call(make_app(Config()), "/gallery")[0].startswith("404")


def test_no_order_or_money_movement_controls_anywhere(demo):
    app, _ = demo
    for route in ROUTES + ["/gallery", "/market?venue=kalshi&id=DEMO-B67.5&side=YES"]:
        body = text(call(app, route)[2]).lower()
        assert 'method="post"' not in body and "<button" not in body.replace('<button class="tape-btn"', "").replace(
            '<button class="btn btn-primary" type="submit">apply filters', ""), route
        for word in (">buy<", ">sell<", ">deposit<", ">withdraw<", ">place order", ">approve", ">submit order"):
            assert word not in body, (route, word)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_new_routes_are_read_only(demo, method):
    app, _ = demo
    for route in ROUTES + ["/market", "/gallery", f"/static/{h.asset_version()}/tokens.css"]:
        status, headers, _ = call(app, route, method=method)
        assert status.startswith("405") and headers["Allow"] == "GET, HEAD", route


# --------------------------------------------------------------------------- query parameters


@pytest.mark.parametrize("query", [
    "domain=weather%27%3B--", "state=everything", "horizon=soon", "sort=random()", "account=real",
    "venue=kalshi.evil", "venue=../../etc", "page=0", "page=1001", "page=-1", "page=1e3", "q=" + "x" * 121,
    "q=a%00b", "state=qualified&state=blocked", "sport=nfl",
])
def test_invalid_filters_are_a_safe_400(demo, query):
    app, _ = demo
    status, headers, body = call(app, "/opportunities?" + query)
    body = text(body)
    assert status.startswith("400") and "Unsupported filter" in body and "Traceback" not in body
    assert headers["Cache-Control"] == "no-store"


def test_valid_filters_render_and_search_is_escaped(demo):
    app, _ = demo
    for query in ("domain=weather", "state=qualified", "horizon=over7", "sort=title", "venue=kalshi", "page=1",
                  "account=research", "q=67", "domain=sports", "q=%3Cscript%3Ealert(1)%3C%2Fscript%3E"):
        status, _, body = call(app, "/opportunities?" + query)
        assert status == "200 OK", query
        assert "<script>alert(1)" not in text(body)
    body = text(call(app, "/opportunities?q=%3Cscript%3E")[2])
    assert 'value="&lt;script&gt;"' in body


def test_unknown_parameters_are_ignored_not_executed(demo):
    app, _ = demo
    plain = call(app, "/risk")[2]
    assert call(app, "/risk?sql=DROP%20TABLE%20x&path=/etc/passwd&cmd=rm")[2] == plain


def test_filters_narrow_and_empty_matches_offer_clear_filters(demo):
    app, _ = demo
    weather = text(call(app, "/opportunities?domain=weather")[2]).split("All recorded decisions")[0]
    assert "DEMO-B67.5" in weather and "DEMO-SENATE-VOTE" not in weather
    none = text(call(app, "/opportunities?q=no-such-market-anywhere")[2])
    assert "No matches in captured data" in none and "Clear filters" in none
    sports = text(call(app, "/opportunities?domain=sports")[2])
    assert "No sport or league data connected" in sports and "not a verified zero-market result" in sports


def test_market_detail_validates_identity(demo):
    app, _ = demo
    status, _, body = call(app, "/market?venue=kalshi&id=DEMO-B67.5&side=NO")
    body = text(body)
    assert status == "200 OK" and "Read-only · Trading disabled" in body and "Rules &amp; evidence" in body
    for section in ("Quote", "Price history", "Our assessment", "Across venues", "Capital &amp; timing",
                    "Decision preview"):
        assert f">{section}</h2>" in body, section
    assert body.index(">Quote</h2>") < body.index(">Our assessment</h2>") < body.index(">Across venues</h2>")
    assert call(app, "/market?venue=kalshi&id=DEMO-NOPE")[0].startswith("404")
    assert call(app, "/market?venue=kalshi&id=..%2F..%2Fetc")[0].startswith("400")
    assert call(app, "/market?venue=nowhere&id=DEMO-B67.5")[0].startswith("400")
    assert call(app, "/market")[0].startswith("404")


# --------------------------------------------------------------------------- honest states


def test_early_state_is_not_shown_as_healthy(early_app):
    body = text(call(early_app, "/")[2])
    assert "Capture needs attention · Sep 23" in body and "Missing forecast and decision evidence." in body
    assert "Report refreshed 11 min ago" in body
    assert "healthy" not in body.lower().split("system &amp; evidence")[0]
    assert "No quotes captured yet." in body and "No markets captured yet" in body
    assert "Realized today" in body and "not computed" in body  # unavailable, never $0.00


def test_early_state_every_page_renders_honest_empty_states(early_app):
    pages = {r: text(call(early_app, r)[2]) for r in ROUTES}
    assert "Not evaluated yet" in pages["/positions"]
    assert "No linked positions" in pages["/outcome-board"]
    assert "Waiting for first capture" in pages["/opportunities"]
    assert "0 of 180 valid forward days" in pages["/experiments"]
    assert "Nothing needs attention" not in pages["/alerts"]  # the invalid capture shows up as attention


def test_known_zero_unknown_and_error_are_distinct(tmp_path):
    empty = text(call(make_app(Config()), "/")[2])
    assert "$0.00" not in empty and "not started" in empty.lower()
    cfg, _ = early(tmp_path)
    known = text(call(make_app(cfg), "/")[2])
    assert "$0.00" in known  # an opened account with nothing committed: a known zero
    bad = tmp_path / "bad.sqlite3"
    bad.write_bytes(b"not sqlite" * 50)
    broken = text(call(make_app(Config(ledger=bad)), "/positions")[2])
    assert "Ledger could not be loaded" in broken and "This is not an empty portfolio" in broken


def test_unknown_state_codes_are_neutral_and_keep_their_code():
    out = c.badge("SOMETHING_NEW")
    assert "k-nd" in out and "code: SOMETHING_NEW" in out
    assert pr.state_word(None).kind == "warn"


def test_every_engine_reason_has_a_plain_label():
    from edge_lab.opportunity import Reason
    for reason in Reason:
        assert reason.value in pr.STATES, reason


# --------------------------------------------------------------------------- account scope


def test_research_scope_never_changes_or_sums_operational_figures(demo):
    app, cfg = demo
    ledger = ShadowLedger.open_readonly(cfg.ledger)
    op = ledger.state(shadow.ACCOUNT_ID)
    rs = ledger.state(shadow.RESEARCH_ACCOUNT_ID)
    op_page = text(call(app, "/positions")[2])
    rs_page = text(call(app, "/positions?account=research")[2])
    assert pr.money(op.equity) in op_page and "FROZEN RESEARCH RULE" not in op_page.split("<main")[1]
    assert pr.money(rs.equity) in rs_page and "FROZEN RESEARCH RULE" in rs_page
    assert pr.money(op.equity + rs.equity) not in op_page + rs_page
    assert text(call(app, "/positions")[2]) == op_page  # rendering research changed nothing


# --------------------------------------------------------------------------- formatting


@pytest.mark.parametrize("value,expected", [
    ("1000", "$1,000.00"), ("0", "$0.00"), ("0.0158", "$0.0158"), ("-3.2", "−$3.20"), ("12345678.9012", "$12,345,678.9012"),
    (None, None), ("nan", None), ("abc", None)])
def test_money(value, expected):
    assert pr.money(value) == expected


@pytest.mark.parametrize("value,expected", [("0.48", "48¢"), ("0.4825", "48.25¢"), ("0.005", "0.5¢"), ("1", "100¢"),
                                            (None, None)])
def test_cents(value, expected):
    assert pr.cents(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("0.0512", "+5.12¢"), ("-0.0003", "−0.03¢"), ("-0.00001", "−<0.01¢"), ("0.00009", "+<0.01¢"), ("0", "0¢"),
    ("0.05129", "+5.12¢"), ("-0.05129", "−5.12¢")])
def test_edge_rounds_toward_zero_and_keeps_its_sign(value, expected):
    assert pr.edge_cents(value) == expected


def test_probability_points_are_not_percent():
    assert pr.pp(Decimal("0.052")) == "+5.2 pp" and pr.percent("0.64") == "64.0%"
    assert pr.pp("-0.0004") == "−<0.1 pp"


def test_new_york_times_follow_daylight_saving():
    assert pr.time_et("2026-09-23T21:45:00+00:00") == "5:45 PM EDT"
    assert pr.time_et("2026-12-23T22:45:00+00:00") == "5:45 PM EST"
    assert pr.datetime_et("2026-09-23T04:10:00Z") == "Sep 23, 12:10 AM EDT"
    assert pr.time_et(None) is None and pr.time_et("not a time") is None


def test_missing_values_render_as_accessible_unavailable_marker():
    out = c.money_cell(None)
    assert "—" in out and 'aria-label="unavailable"' in out and "$" not in out


# --------------------------------------------------------------------------- the board


def test_board_states_come_from_recorded_verdicts():
    from edge_lab.dashboard.fixtures import synthetic_rows
    rows = {r.native_id: r for r in synthetic_rows()}
    assert rows["DEMO-HIGHNY-B67.5"].state == "qualified"
    assert rows["DEMO-NFL-KCBUF"].state == "watching"  # NO_EDGE: observed, not qualified
    assert rows["DEMO-SENATE-VOTE"].state == "blocked"  # BOOK_STALE
    assert rows["DEMO-CPI-OCT"].state == "blocked" and rows["DEMO-CPI-OCT"].cash_release[0] == "over7"
    assert rows["DEMO-UFC-MAINEVENT"].state == "unsupported"
    assert rows["DEMO-LONG-UNICODE"].state == "watching" and rows["DEMO-LONG-UNICODE"].primary is None


def test_default_sort_puts_qualified_edges_first_and_unknowns_last():
    from edge_lab.dashboard.fixtures import synthetic_rows
    ordered = pr.sort_rows(synthetic_rows())
    assert ordered[0].native_id == "DEMO-HIGHNY-B67.5"
    assert [r.native_id for r in pr.sort_rows(synthetic_rows(), "edge")][-1] in ("DEMO-UFC-MAINEVENT",
                                                                                  "DEMO-LONG-UNICODE")


def test_tape_uses_captured_quotes_only(demo):
    app, _ = demo
    body = text(call(app, "/")[2])
    tape = body.split('data-tape>')[1].split("</ul>")[0]
    assert 0 < tape.count('class="tape-item"') <= 12
    assert "LIVE" not in tape and "captured" in tape
    assert 'href="/market?' in tape
    empty = text(call(make_app(Config()), "/")[2])
    assert "No quotes captured yet." in empty


def test_price_change_needs_two_comparable_observations():
    from edge_lab.dashboard.data import ObservedMarket, ObservedQuote
    q = lambda ask, at: ObservedQuote("YES", Decimal(ask) if ask else None, None, Decimal(1), at, "s", None)  # noqa
    one = ObservedMarket("kalshi", "kalshi:X", "X", None, None, "weather", "2026-09-24", None, "x", None, None, None,
                         None, "binary", {"decision": {"YES": q("0.30", "t0")}})
    assert pr.observed_quotes(one)["YES"].change is None
    two = ObservedMarket("kalshi", "kalshi:X", "X", None, None, "weather", "2026-09-24", None, "x", None, None, None,
                         None, "binary", {"decision": {"YES": q("0.30", "t0")}, "recheck": {"YES": q("0.32", "t1")}})
    assert pr.observed_quotes(two)["YES"].change == Decimal("0.02")
    gap = ObservedMarket("kalshi", "kalshi:X", "X", None, None, "weather", "2026-09-24", None, "x", None, None, None,
                         None, "binary", {"decision": {"YES": q(None, "t0")}, "recheck": {"YES": q("0.32", "t1")}})
    assert pr.observed_quotes(gap)["YES"].change is None


def test_single_observation_is_never_drawn_as_a_trend():
    out = c.history_chart([("2026-09-23T22:00:00Z", "0.34")], label="x")
    assert "<polyline" not in out and "Not enough history for a chart" in out
    two = c.history_chart([("2026-09-23T22:00:00Z", "0.34"), ("2026-09-23T22:12:00Z", "0.36")], label="x")
    assert "<polyline" in two and "captured (ET)" in two


# --------------------------------------------------------------------------- independent review fixes


def _decision(market_id, target, qualify=True, side="YES", edge="0.07"):
    return {"decision_id": f"dec-{market_id}-{target}-{side}", "slot": f"{target}|{market_id}|{side}",
            "as_of_utc": f"{target}T22:00:00+00:00", "market_id": market_id, "side": side,
            "event_id": "weather:x", "qualification": "QUALIFY" if qualify else "REJECT",
            "reason": "QUALIFY" if qualify else "NO_EDGE", "reasons": [] if qualify else ["NO_EDGE"],
            "opportunity": {"model_probability": "0.5", "net_edge": edge, "executable_price": "0.4"}}


def _observed(market_id, target, status="complete"):
    from edge_lab.dashboard.data import ObservedMarket, ObservedQuote
    q = ObservedQuote("YES", Decimal("0.40"), None, Decimal(5), f"{target}T21:55:00+00:00", "s:1", None)
    return ObservedMarket("kalshi", market_id, market_id.split(":")[1], None, "weather:x", "weather", target, "T", "o",
                          None, None, None, None, "binary", {"decision": {"YES": q}})


def test_decisions_for_earlier_target_days_are_never_current():
    old = _decision("kalshi:A", "2026-09-20")
    now_ = _decision("kalshi:B", "2026-09-23")
    rows = {r.native_id: r for r in pr.build_rows(
        [_observed("kalshi:A", "2026-09-23"), _observed("kalshi:B", "2026-09-23")], "acct", [old, now_], {},
        current_target="2026-09-23")}
    assert rows["A"].state == "watching" and rows["A"].primary is None and len(rows["A"].history) == 1
    assert rows["B"].state == "qualified"
    gone = pr.build_rows([], "acct", [_decision("kalshi:OLD", "2026-09-20"), _decision("kalshi:NEW", "2026-09-23")],
                         {})
    states = {r.native_id: r.state for r in gone}
    assert states == {"OLD": "historical", "NEW": "qualified"}
    ordered = pr.sort_rows(gone)
    assert ordered[-1].native_id == "OLD" and pr.sort_rows(gone, "edge")[-1].native_id == "OLD"
    assert [r.native_id for r in pr.filter_rows(gone, pr.Params(state="qualified"))] == ["NEW"]


def test_demo_board_counts_only_current_day_decisions_as_qualified(demo):
    app, _ = demo
    body = text(call(app, "/")[2])
    assert "Historical decision" in body or "not evaluated for this target day" in body


def test_incomplete_captures_are_labelled_everywhere():
    from edge_lab.dashboard.data import ObservedBoard
    from edge_lab.dashboard.views.common import coverage_text
    board = ObservedBoard("2026-09-23", {"decision": {"status": "partial", "completed_at_utc": "2026-09-22T22:00:00Z"}},
                          [_observed("kalshi:A", "2026-09-23")], 1)
    assert "capture incomplete" in coverage_text(board)
    rows = pr.build_rows(board.markets, "acct", [], {}, capture_status={"decision": "partial"})
    q = rows[0].quotes["YES"]
    assert not q.capture_complete
    assert "capture incomplete" in c.market_row(rows[0], pr.Params())
    assert "Capture incomplete" in c.tape([(rows[0], q)], pr.Params())
    big = ObservedBoard("2026-09-23", {"decision": {"status": "complete"}}, [], 250)
    assert "of 250 markets shown" in coverage_text(big)


def test_quote_labels_carry_a_date_and_the_engine_book_age_rule(demo):
    app, _ = demo
    detail = text(call(app, "/market?venue=kalshi&id=DEMO-B67.5&side=YES")[2])
    assert "Stale quote — not actionable" in detail  # captured ~20 h ago, far past the engine's book-age limit
    board = text(call(app, "/opportunities")[2])
    assert re.search(r"Captured [A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d{2} [AP]M E[DS]T", board)


@pytest.mark.parametrize("page", ["%C2%B2", "%D9%A3", "1%00"])
def test_unicode_digits_in_page_are_a_safe_400(demo, page):
    app, _ = demo
    status, _, body = call(app, f"/opportunities?page={page}")
    assert status.startswith("400") and "Unsupported filter" in text(body)


def test_detail_sections_follow_one_side():
    from edge_lab.dashboard.fixtures import synthetic_rows
    from edge_lab.dashboard.views.markets import capital_section, ticket_section
    row = next(r for r in synthetic_rows() if r.native_id == "DEMO-HIGHNY-B67.5")
    assert row.for_side("NO") is None and row.for_side("YES") is not None
    assert "Size not evaluated" in capital_section(row, "NO") and "No decision to preview" in ticket_section(
        row, "NO", pr.Params())


def test_weekday_is_new_york_not_utc(tmp_path):
    late = datetime(2026, 9, 24, 2, 30, tzinfo=timezone.utc)  # Wednesday 10:30 PM EDT
    body = text(call(make_app(Config(clock=lambda: late)), "/")[2])
    assert "Wednesday, Sep 23, 10:30 PM EDT" in body and "Thursday" not in body


def test_cash_release_within_seven_days_needs_an_eligible_verdict():
    from edge_lab.dashboard.fixtures import synthetic_rows
    row = synthetic_rows()[0]
    delayed = dataclasses.replace(row.primary, starter={"eligible": False, "reasons": ["DELAYED_OR_DISPUTED"],
                                                        "tradable_cash_release_eta_utc": "2026-09-25T00:00:00Z"})
    assert dataclasses.replace(row, assessments=(delayed,)).cash_release[0] == "unknown"
    assert row.cash_release[0] == "within7"
