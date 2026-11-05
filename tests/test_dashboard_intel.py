"""The news & political intelligence workspace (/experiments/intel, #192, ADR 0049, UI_CONTRACT §14 2026-11-05).

Stores are built through the real intel service API (no network): collected items through
`insert_intel_items` / `record_intel_fetch`, a transcript, the recorded packet, an imported analysis, an
owner-confirmed link and decisions from `service.decide` over the labelled FIXTURE Kalshi payloads.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from edge_lab.dashboard import intel_fixtures
from edge_lab.dashboard.app import make_app
from edge_lab.dashboard.data import Config
from edge_lab.intel import service
from edge_lab.intel.analysis_import import extract_object
from edge_lab.storage import SnapshotStore

FIX = Path(__file__).parent / "fixtures" / "intel" / "kalshi"
NOW = datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc)
HOST = "127.0.0.1:8765"
ORIGIN = f"http://{HOST}"
TABS = ("today", "opportunities", "events", "transcripts", "history", "sources")
LABELS = ("COLLECTED (automatic)", "CLASSIFIED (deterministic rules, intel-extract-v1)",
          "IMPORTED AI ANALYSIS (unvalidated)", "PROVISIONAL FORECAST (no calibration history)",
          "ECONOMICS: ESTIMATE — fees unverified")
EVIL = "<script>alert(1)</script> Jane Doe impeachment articles filed"
POL, CPI = "KXPOLFIXTURE-26DEC31-Y", "KXCPI-26DEC-T0.3"


# --------------------------------------------------------------------------- builders


def _fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _items(store, *, extra=()):
    intel_fixtures.add_items(store, NOW, intel_fixtures.HEADLINES + tuple(extra), run="intel-test-news")


def _analysis(store, event_id, *, abstain=False, owner=False):
    packet = service.latest_packet_for_event(store, event_id)
    obj = extract_object(packet.text)
    obj["assistant"] = "Test assistant"
    obj["summary"] = "Articles filed; no vote scheduled."
    for o in obj["outcomes"]:
        if abstain:
            o.update(abstain=True, reasoning="cannot say", main_risk="unknown")
        else:
            o.update(probability=0.55, low=0.47, high=0.62, reasoning="E1 says filed", key_evidence_ids=["E1"],
                     main_risk="tabled")
    return service.import_analysis(store, "```json\n" + json.dumps(obj) + "\n```", now=NOW - timedelta(minutes=30),
                                   owner_judgment=owner)


def _event(store):
    return next(e for e in service.current_events(store, now=NOW) if e.topic.value == "IMPEACHMENT")


def _decide(store, ticker, outcome, *, received=NOW, at=NOW):
    market = _fixture(f"market_{ticker}.json")
    book = _fixture(f"orderbook_{ticker}.json")
    link = service.record_link(store, outcome_id=outcome, ticker=ticker, status="CONFIRMED", rules_read=True,
                               yes_matches_outcome=True, now=at - timedelta(minutes=1))
    return service.decide(store, link=link, market=market, orderbook=book, received_at_utc=received.isoformat(),
                          evidence_id="snapshot:test", now=at)


def build(tmp_path: Path, state: str, *, heartbeat: str | None = "fresh", inbox: bool = True) -> Config:
    """A Config over a store in `state`: empty, populated, stale, unsupported, insufficient, error."""
    db = tmp_path / "evidence.sqlite3"
    status = tmp_path / "status"
    status.mkdir(parents=True, exist_ok=True)
    if state == "error":
        db.write_bytes(b"not a database")
    else:
        store = SnapshotStore(db)
        if state != "empty":
            _items(store, extra=(("bbc", "bbc_top", "bbc", 1, EVIL, "<b>bold</b> injected"),))
            service.import_transcript(store, data=intel_fixtures.TRANSCRIPT.encode(), now=NOW - timedelta(hours=1),
                                      meta={"podcast": "Test Pod", "episode": "E1 (TEST TRANSCRIPT)",
                                            "published_date": "2026-11-04", "transcript_source": "test fixture"})
            ev = _event(store)
            _analysis(store, ev.event_id, abstain=state == "insufficient")
            outcome = next(o.outcome_id for o in ev.outcomes if o.slug == "impeached")
            if state == "unsupported":
                _decide(store, CPI, outcome)
            elif state == "stale":
                _decide(store, POL, outcome, received=NOW - timedelta(hours=3), at=NOW - timedelta(hours=2))
            else:
                _decide(store, POL, outcome)
    beat = {"fresh": NOW - timedelta(minutes=2), "old": NOW - timedelta(hours=6)}.get(heartbeat or "")
    if beat is not None:
        (status / "intel.json").write_text(json.dumps({"schema": "intel-heartbeat/1", "at_utc": beat.isoformat()}))
    root = tmp_path / "inbox"
    if inbox:
        root.mkdir(exist_ok=True)
    return Config(db=db, status_dir=status, intel_inbox=root if inbox else None, clock=lambda: NOW)


def call(app, path, *, method="GET", query="", body=b"", ctype=None, origin=ORIGIN, host=HOST, extra=None):
    out = {}

    def start(status, headers):
        out["status"], out["headers"] = status, dict(headers)

    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "HTTP_HOST": host,
               "wsgi.input": io.BytesIO(body), "CONTENT_LENGTH": str(len(body)) if method == "POST" else ""}
    if origin is not None:
        environ["HTTP_ORIGIN"] = origin
    if ctype:
        environ["CONTENT_TYPE"] = ctype
    environ.update(extra or {})
    text = b"".join(app(environ, start)).decode("utf-8")
    return out["status"], out["headers"], text


def visible(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def token_of(app) -> str:
    _, _, body = call(app, "/experiments/intel")
    return re.search(r'name="token" value="([^"]+)"', body).group(1)


def form(fields: dict) -> tuple[bytes, str]:
    from urllib.parse import urlencode
    return urlencode(fields).encode(), "application/x-www-form-urlencoded"


def multipart(fields: dict, files: dict | None = None) -> tuple[bytes, str]:
    boundary = "----edgelabtestboundary7MA4YWxkTrZu0gW"
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'.encode() + v.encode()
                     + b"\r\n")
    for k, (name, data, ctype) in (files or {}).items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
                     f"Content-Type: {ctype}\r\n\r\n".encode() + data + b"\r\n")
    return b"".join(parts) + f"--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def files_digest(*paths: Path) -> dict[str, str]:
    out = {}
    for root in paths:
        for p in sorted(root.rglob("*")) if root.is_dir() else [root]:
            if p.is_file():
                out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# --------------------------------------------------------------------------- rendering states


@pytest.mark.parametrize("state", ["empty", "populated", "stale", "unsupported", "insufficient", "error"])
@pytest.mark.parametrize("tab", TABS)
def test_every_tab_renders_in_every_state(tmp_path, state, tab):
    app = make_app(build(tmp_path, state))
    status, headers, body = call(app, "/experiments/intel", query=f"tab={tab}")
    assert status == "200 OK", body[-500:]
    text = visible(body)
    assert "SHADOW · NO REAL MONEY" in text and "News &amp; political intelligence" in text
    assert not re.search(r"\bBUY\b", text, re.I) and ">buy<" not in body.lower()
    assert "<script>alert" not in body and ' style="' not in body and not re.search(r"<[^>]+\son[a-z]+=", body)
    assert headers["Referrer-Policy"] == "same-origin" and headers["Cache-Control"] == "no-store"
    if state == "error":
        assert "Intelligence workspace unavailable" in text and 'role="alert"' in body
        assert 'method="post"' not in body
    else:
        assert 'href="/experiments"' in body  # crumb back to Research & Data


def test_populated_shows_provenance_labels_and_the_opportunity(tmp_path):
    app = make_app(build(tmp_path, "populated"))
    text = visible(call(app, "/experiments/intel", query="tab=opportunities")[2])
    for label in LABELS[2:]:
        assert label in text, label
    assert "HYPOTHETICAL RESEARCH DECISION" in text and POL in text
    assert "Investigate · not a trade" in text  # the fixture's conservative EV is positive: a lead, not a trade
    assert "not a claimable edge" in text  # the stored explanation, verbatim
    assert "ECONOMICS: ESTIMATE — fees unverified" in text
    assert '<p class="eyebrow">ECONOMICS: VERIFIED</p>' not in call(app, "/experiments/intel", query="tab=opportunities")[2]
    today = visible(call(app, "/experiments/intel")[2])
    assert LABELS[0] in today and "Today&#x27;s intelligence" in today
    assert LABELS[1] in visible(call(app, "/experiments/intel", query="tab=events")[2])


def test_injection_in_a_headline_is_escaped(tmp_path):
    app = make_app(build(tmp_path, "populated"))
    body = call(app, "/experiments/intel")[2]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body and "<script>alert(1)" not in body
    assert "&lt;b&gt;bold&lt;/b&gt;" in body
    for link in re.findall(r'<a class="link" href="([^"]+)" rel="noopener noreferrer"', body):
        assert link.startswith(("https://", "http://"))


def test_insufficient_evidence_is_said_in_words(tmp_path):
    app = make_app(build(tmp_path, "insufficient"))
    text = visible(call(app, "/experiments/intel", query="tab=opportunities")[2])
    assert "INSUFFICIENT EVIDENCE — NO RELIABLE EDGE ESTIMATE" in text
    assert "Insufficient evidence" in text


def test_unsupported_fee_reads_fee_unsupported(tmp_path):
    app = make_app(build(tmp_path, "unsupported"))
    text = visible(call(app, "/experiments/intel", query="tab=opportunities")[2])
    assert "ECONOMICS: FEE UNSUPPORTED" in text and "FEE_UNSUPPORTED" in text and CPI in text


def test_stale_decision_and_old_heartbeat_are_not_current(tmp_path):
    app = make_app(build(tmp_path, "stale", heartbeat="old"))
    text = visible(call(app, "/experiments/intel", query="tab=opportunities")[2])
    assert "Price evidence is not current" in text and "stale — not actionable" in text
    assert "Collector not processing submissions" in text and "last heartbeat 6 h ago" in text
    assert 'method="post"' in call(app, "/experiments/intel")[2]  # forms still queue, and say so


def test_blocked_without_heartbeat_and_not_enabled_without_inbox(tmp_path):
    app = make_app(build(tmp_path, "populated", heartbeat=None))
    text = visible(call(app, "/experiments/intel")[2])
    assert "The news collector is not running on this host" in text and "never recorded" in text
    app2 = make_app(build(tmp_path / "b", "empty", inbox=False))
    body = call(app2, "/experiments/intel", query="tab=transcripts")[2]
    assert "Submissions are not enabled on this dashboard" in visible(body)
    assert "<form" not in body and "<button" not in body.replace('<button class="tape-btn"', "")


def test_empty_store_reads_waiting(tmp_path):
    app = make_app(build(tmp_path, "empty"))
    text = visible(call(app, "/experiments/intel")[2])
    assert "Waiting for first collection" in text
    assert "No confirmed market yet" in visible(call(app, "/experiments/intel", query="tab=opportunities")[2])
    sources = visible(call(app, "/experiments/intel", query="tab=sources")[2])
    assert "50 candidates" in sources


def test_event_detail_and_packet_page(tmp_path):
    cfg = build(tmp_path, "populated")
    app = make_app(cfg)
    store = SnapshotStore.open_readonly(cfg.db)
    ev = _event(store)
    body = call(app, "/experiments/intel", query=f"tab=events&event={ev.event_id}")[2]
    text = visible(body)
    for words in ("Open research packet", "Find Kalshi markets", "Prepare research packet", "Paste analysis",
                  "This is my own judgment, not an assistant", "Resolves on", "Unconfirmed podcast claims"):
        assert words in text.replace("&#x27;", "'"), words
    status, headers, page = call(app, "/experiments/intel/packet", query=f"event={ev.event_id}")
    assert status == "200 OK" and headers["Referrer-Policy"] == "same-origin"
    packet_text = re.search(r'<textarea class="input mono" id="packet-text"[^>]*>(.*?)</textarea>', page, re.S).group(1)
    assert "MARKET EDGE RESEARCH PACKET" in packet_text
    for banned in ("KXPOL", "KXCPI", "kalshi", "38¢", "0.38", "orderbook"):
        assert banned.lower() not in packet_text.lower(), banned
    assert 'data-copy-target="packet-text"' in page and " hidden>" in page  # revealed by terminal.js only
    assert len(re.findall(r"<script[^>]*>", page)) == 1 and "terminal.js" in re.findall(r"<script[^>]*>", page)[0]


def test_packet_page_without_a_packet_offers_the_prepare_form(tmp_path):
    app = make_app(build(tmp_path, "empty"))
    text = visible(call(app, "/experiments/intel/packet", query="event=ev-impeachment-0123456789ab")[2])
    assert "No research packet recorded yet" in text and "Prepare research packet" in text


@pytest.mark.parametrize("query", ["tab=orders", "event=../../etc", "event=ev-x-1", "submitted=x;rm", "tab=a&tab=b"])
def test_bad_parameters_are_a_safe_400(tmp_path, query):
    app = make_app(build(tmp_path, "empty"))
    status, _, body = call(app, "/experiments/intel", query=query)
    assert status.startswith("400") and "Unsupported filter" in body


def test_get_and_head_write_nothing(tmp_path):
    cfg = build(tmp_path, "populated")
    (cfg.intel_inbox / "new").mkdir(parents=True)
    app = make_app(cfg)
    # A read-only open of a WAL database lets SQLite create its empty -wal/-shm side files (ADR 0024 amendment
    # 2026-09-24); read once first, then every byte under tmp_path must stay identical.
    store = SnapshotStore.open_readonly(cfg.db)
    ev = _event(store)
    before = files_digest(tmp_path)
    for tab in TABS:
        call(app, "/experiments/intel", query=f"tab={tab}")
        call(app, "/experiments/intel", method="HEAD", query=f"tab={tab}")
    call(app, "/experiments/intel", query=f"tab=events&event={ev.event_id}")
    call(app, "/experiments/intel/packet", query=f"event={ev.event_id}")
    assert files_digest(tmp_path) == before


def test_research_tab_links_the_workspace_without_a_form(tmp_path):
    app = make_app(build(tmp_path, "empty"))
    body = call(app, "/experiments")[2]
    assert 'href="/experiments/intel"' in body and "<form" not in body


# --------------------------------------------------------------------------- the one POST route


def _post(app, fields, *, token=None, files=None, **kw):
    fields = {"token": token if token is not None else token_of(app), **fields}
    body, ctype = multipart(fields, files) if files is not None else form(fields)
    return call(app, "/experiments/intel/inbox", method="POST", body=body, ctype=ctype, **kw)


def _inbox_files(cfg):
    return sorted((cfg.intel_inbox / "new").glob("*.json")) if (cfg.intel_inbox / "new").is_dir() else []


def test_post_happy_path_writes_exactly_one_inbox_file(tmp_path):
    cfg = build(tmp_path, "populated")
    app = make_app(cfg)
    db_before = files_digest(cfg.db, cfg.status_dir)
    status, headers, _ = _post(app, {"kind": "refresh", "scope": "news", "return_tab": "history"})
    assert status == "303 See Other"
    files = _inbox_files(cfg)
    assert len(files) == 1
    sub = json.loads(files[0].read_text())
    assert sub["kind"] == "refresh" and sub["payload"] == {"scope": "news"}
    assert headers["Location"] == f"/experiments/intel?tab=history&submitted={sub['id']}"
    assert files_digest(cfg.db, cfg.status_dir) == db_before  # the evidence DB is never written
    shown = visible(call(app, "/experiments/intel", query=headers["Location"].split("?", 1)[1])[2])
    assert f"Submission queued · {sub['id']}" in shown and "Queued" in shown


def test_post_transcript_upload_and_link_and_packet(tmp_path):
    cfg = build(tmp_path, "populated")
    app = make_app(cfg)
    meta = {"kind": "transcript", "podcast": "P", "episode": "E9", "transcript_source": "owner paste",
            "published_date": "2026-11-04", "return_tab": "transcripts"}
    status, _, _ = _post(app, {**meta, "text": ""}, files={"file": ("ep.vtt", b"WEBVTT\n\n00:00:01.000 --> "
                                                                        b"00:00:02.000\nHello there.\n", "text/vtt")})
    assert status == "303 See Other"
    sub = json.loads(_inbox_files(cfg)[0].read_text())
    assert sub["payload"]["filename"] == "ep.vtt" and sub["payload"]["meta"]["podcast"] == "P"
    store = SnapshotStore.open_readonly(cfg.db)
    ev = _event(store)
    outcome = f"{ev.event_id}:impeached"
    status, _, body = _post(app, {"kind": "link", "outcome_id": outcome, "ticker": "KXPOLFIXTURE-26DEC31-N",
                                  "status": "CONFIRMED"})
    assert status.startswith("400") and "tick both boxes" in visible(body)
    status, _, _ = _post(app, {"kind": "link", "outcome_id": outcome, "ticker": "KXPOLFIXTURE-26DEC31-N",
                               "status": "CONFIRMED", "rules_read": "yes", "yes_matches_outcome": "yes"})
    assert status == "303 See Other"
    status, _, body = _post(app, {"kind": "link", "outcome_id": outcome, "ticker": "KXHIGHNY-26NOV05-B60",
                                  "status": "REJECTED"})
    assert status.startswith("400") and "protected" in visible(body)
    assert _post(app, {"kind": "packet", "event_id": ev.event_id, "horizon_date": "2027-03-31"})[0] == "303 See Other"
    assert _post(app, {"kind": "packet", "event_id": ev.event_id, "horizon_date": "2020-01-01"})[0].startswith("400")
    kinds = sorted(json.loads(p.read_text())["kind"] for p in _inbox_files(cfg))
    assert kinds == ["link", "packet", "transcript"]


def test_post_analysis_is_validated_on_submit(tmp_path):
    cfg = build(tmp_path, "populated")
    app = make_app(cfg)
    status, _, body = _post(app, {"kind": "analysis", "text": "no json here"}, files={})
    assert status.startswith("400") and "does not validate" in visible(body)
    store = SnapshotStore.open_readonly(cfg.db)
    obj = extract_object(service.latest_packet_for_event(store, _event(store).event_id).text)
    for o in obj["outcomes"]:
        o.update(probability=0.4, low=0.3, high=0.5, reasoning="r", main_risk="m")
    obj["assistant"], obj["summary"] = "Me", "s"
    status, _, _ = _post(app, {"kind": "analysis", "text": json.dumps(obj), "owner_judgment": "yes"}, files={})
    assert status == "303 See Other"
    payload = json.loads(_inbox_files(cfg)[0].read_text())["payload"]
    assert payload["owner_judgment"] is True


@pytest.mark.parametrize("data,code", [(b"\xff\xfe\x00bad", "415"), (b"ok", "415")])
def test_post_upload_must_be_utf8_text_with_a_known_suffix(tmp_path, data, code):
    cfg = build(tmp_path, "empty")
    app = make_app(cfg)
    name = "ep.txt" if data.startswith(b"\xff") else "ep.exe"
    status, _, body = _post(app, {"kind": "transcript", "podcast": "P", "episode": "E", "transcript_source": "s"},
                            files={"file": (name, data, "application/octet-stream")})
    assert status.startswith(code) and _inbox_files(cfg) == []
    assert "Back to the workspace" in body and "nothing was written" in body


def test_post_refusals(tmp_path):
    cfg = build(tmp_path, "empty")
    app = make_app(cfg)
    ok = {"kind": "refresh", "scope": "news"}
    assert _post(app, ok, token="forged")[0].startswith("403")
    assert _post(app, ok, origin="https://evil.example")[0].startswith("403")
    assert _post(app, ok, origin="null")[0].startswith("403")
    assert _post(app, ok, origin=None)[0].startswith("403")  # neither Origin nor Referer
    assert _post(app, ok, origin=None, extra={"HTTP_REFERER": f"{ORIGIN}/experiments/intel"})[0] == "303 See Other"
    assert _post(app, ok, host="localhost:8765", origin="http://127.0.0.1:8765")[0].startswith("403")
    assert _post(app, {"kind": "orders"})[0].startswith("400")
    assert _post(app, {"kind": "refresh", "scope": "everything"})[0].startswith("400")
    big = b"x" * 1_600_001
    status = call(app, "/experiments/intel/inbox", method="POST", body=big,
                  ctype="application/x-www-form-urlencoded")[0]
    assert status.startswith("413")
    status = call(app, "/experiments/intel/inbox", method="POST", body=b"a=b", ctype="application/json")[0]
    assert status.startswith("415")
    status = call(app, "/experiments/intel/inbox", method="POST", body=b"a=b", ctype="application/x-www-form-urlencoded",
                  extra={"CONTENT_LENGTH": ""})[0]
    assert status.startswith("411")
    status = call(app, "/experiments/intel/inbox", method="POST", body=b"kind=refresh",
                  ctype="application/x-www-form-urlencoded", host="evil.example")[0]
    assert status.startswith("400")  # Host allowlist first
    assert len(_inbox_files(cfg)) == 1  # only the Referer submission above


def test_a_full_inbox_answers_429(tmp_path, monkeypatch):
    from edge_lab.intel import inbox
    monkeypatch.setattr(inbox, "MAX_INBOX_PENDING", 1)
    cfg = build(tmp_path, "empty")
    app = make_app(cfg)
    assert _post(app, {"kind": "refresh", "scope": "news"})[0] == "303 See Other"
    status, _, body = _post(app, {"kind": "refresh", "scope": "news"})
    assert status.startswith("429") and "already waiting" in visible(body)


def test_post_is_refused_without_an_inbox_and_on_every_other_path(tmp_path):
    cfg = build(tmp_path, "empty", inbox=False)
    app = make_app(cfg)
    token = "x"
    status, headers, body = _post(app, {"kind": "refresh", "scope": "news"}, token=token)
    assert status.startswith("405") and "not enabled" in body and headers["Allow"] == "GET, HEAD"
    app2 = make_app(build(tmp_path / "b", "empty"))
    for path in ("/", "/experiments", "/experiments/intel", "/experiments/intel/packet", "/experiments/intel/inbox/x"):
        status, headers, _ = call(app2, path, method="POST", body=b"kind=refresh",
                                  ctype="application/x-www-form-urlencoded")
        assert status.startswith("405") and headers["Allow"] == "GET, HEAD", path
    for method in ("PUT", "DELETE", "PATCH"):
        assert call(app2, "/experiments/intel/inbox", method=method)[0].startswith("405")
    assert call(app2, "/experiments/intel/inbox")[0].startswith("404")


def test_the_token_is_per_process_and_never_in_a_get_without_inbox(tmp_path):
    cfg = build(tmp_path, "empty")
    assert token_of(make_app(cfg)) != token_of(make_app(cfg))
    body = call(make_app(build(tmp_path / "b", "empty", inbox=False)), "/experiments/intel")[2]
    assert 'name="token"' not in body


# --------------------------------------------------------------------------- demo and gallery


def test_demo_workspace_and_gallery_are_synthetic(tmp_path):
    from edge_lab.dashboard.demo import build_demo
    import shutil

    cfg, root = build_demo()
    try:
        app = make_app(cfg)
        body = call(app, "/experiments/intel", query="tab=opportunities")[2]
        assert "SYNTHETIC UI DEMO" in body and "KXPOLDEMO" in body
        status, _, gallery = call(app, "/gallery/intel")
        text = visible(gallery)
        assert status == "200 OK" and "SYNTHETIC FIXTURES" in text
        for name in ("populated", "today", "stale", "unsupported", "insufficient", "blocked", "not_enabled", "empty",
                     "error"):
            assert f"State · {name}" in text, name
        assert "ECONOMICS: FEE UNSUPPORTED" in text and "INSUFFICIENT EVIDENCE — NO RELIABLE EDGE ESTIMATE" in text
        assert not re.search(r"\bBUY\b", text)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    assert call(make_app(build(tmp_path, "empty")), "/gallery/intel")[0].startswith("404")


def test_intel_rows_keep_their_body_full_width(tmp_path):
    """Regression (390 px demo, 2026-11-05): loose row bodies landed in the grid's aside column and squeezed
    every title to one character per line. Every intel row now wraps its body in .row-body."""
    import re
    from edge_lab.dashboard.views import intel as iv
    html = iv._row("T", sub="s", aside="a", body="<p>long explanation</p><form></form>")
    assert re.search(r'<div class="row-aside">a</div><div class="row-body"><p>long explanation</p><form></form></div></li>$', html)
    css = (Path(__file__).resolve().parents[1] / "src/edge_lab/dashboard/static/terminal.css").read_text()
    assert ".row-body { grid-column: 1 / -1; min-width: 0; }" in css
    src = (Path(__file__).resolve().parents[1] / "src/edge_lab/dashboard/views/intel.py").read_text()
    assert src.count("c.row(") == 1  # only inside _row
