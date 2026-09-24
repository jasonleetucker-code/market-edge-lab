"""The repository cannot place orders or authenticate to a venue (gate 1-2 boundary).

If a future, owner-approved gate needs execution code, it goes in a separate
component with its own review, and this test changes in the same PR as that decision.

One narrow exception exists (ADR 0022): the ntfy notification sink may POST a text body,
with an optional Bearer token, to one topic on an allowlisted ntfy host. Three rules are
relaxed, in exactly one file, and only to POST and the Authorization header. The order, client-write and signing rules
still apply to it, and the tests below prove the exception cannot spread.
"""

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"

FORBIDDEN = {
    "order endpoint": re.compile(r"/portfolio/orders|/orders\b|create_order|place_order|submit_order", re.I),
    "non-GET HTTP method": re.compile(r"""method\s*=\s*["'](POST|PUT|PATCH|DELETE)["']""", re.I),
    "auth header": re.compile(r"""["'](Authorization|KALSHI-ACCESS-KEY|KALSHI-ACCESS-SIGNATURE)["']""", re.I),
    "request body (implies POST)": re.compile(r"\b(Request|urlopen)\([^)]*\bdata\s*="),
    "client write call": re.compile(r"\.(post|put|patch|delete)\(", re.I),
    "request signing": re.compile(r"\b(hmac|rsa|private_key|sign_request)\b", re.I),
}


# The single notification delivery file allowed to publish (ADR 0022), the only rules it is
# relaxed for, and what still applies to it under each (None: the rule is lifted). It may use
# POST only (never PUT, PATCH or DELETE) and the Authorization header only (never a venue
# header). Path-exact: a copy, a rename or a subpackage file gets no exception.
NOTIFICATION_DELIVERY_EXCEPTION = {
    "edge_lab/notify_ntfy.py": {
        "non-GET HTTP method": re.compile(r"""method\s*=\s*["'](PUT|PATCH|DELETE)["']""", re.I),
        "request body (implies POST)": None,
        "auth header": re.compile(r"""["'](KALSHI-ACCESS-KEY|KALSHI-ACCESS-SIGNATURE)["']""", re.I),
    },
}
# These rules have no exception anywhere, the notification file included.
NEVER_EXEMPT = frozenset({"order endpoint", "client write call", "request signing"})


def _source_files():
    return sorted(SRC.rglob("*.py"))


def _rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


def _violations(label: str, rel: str, text: str) -> list[str]:
    """Lines of `text` (the file at `rel`, relative to src/) that break rule `label`."""
    relaxed = NOTIFICATION_DELIVERY_EXCEPTION.get(rel, {})
    pattern = relaxed[label] if label in relaxed else FORBIDDEN[label]
    if pattern is None:
        return []
    return [f"{rel}:{lineno}: {line.strip()}" for lineno, line in enumerate(text.splitlines(), 1)
            if pattern.search(line)]


def test_source_tree_is_scanned():
    assert _source_files(), "no source files found; scan would pass vacuously"


@pytest.mark.parametrize("label", sorted(FORBIDDEN))
def test_no_execution_or_auth_code(label):
    hits = [hit for path in _source_files() for hit in _violations(label, _rel(path), path.read_text())]
    assert not hits, f"{label} found:\n" + "\n".join(hits)


# ---------------------------------------------------------------- the notification exception (ADR 0022)

NTFY_REL = "edge_lab/notify_ntfy.py"
_POST_LINES = {
    "non-GET HTTP method": 'request = Request(url, method="POST")',
    "request body (implies POST)": "request = Request(url, data=body)",
    "auth header": 'headers["Authorization"] = "Bearer x"',
}


def test_the_post_exception_covers_exactly_one_file_and_three_rules():
    assert set(NOTIFICATION_DELIVERY_EXCEPTION) == {NTFY_REL}
    assert (SRC / NTFY_REL).is_file()
    exempt = set(NOTIFICATION_DELIVERY_EXCEPTION[NTFY_REL])
    assert exempt == set(_POST_LINES) and exempt <= set(FORBIDDEN)
    assert not exempt & NEVER_EXEMPT and NEVER_EXEMPT == set(FORBIDDEN) - exempt
    text = (SRC / NTFY_REL).read_text()
    for label in exempt:  # the exception is in use, so it cannot linger after the sink is removed
        assert FORBIDDEN[label].search(text), f"{label}: exception no longer needed; remove it"


@pytest.mark.parametrize("rel", ["edge_lab/notify_ntfy_extra.py", "edge_lab/sub/notify_ntfy.py", "notify_ntfy.py",
                                 "edge_lab/notifications.py", "edge_lab/http.py", "edge_lab/NOTIFY_NTFY.py"])
def test_the_exception_is_bound_to_the_exact_path(rel):
    text = (SRC / NTFY_REL).read_text()
    for label in _POST_LINES:
        assert _violations(label, rel, text), f"{rel} would inherit the {label} exception"


@pytest.mark.parametrize("label", sorted(_POST_LINES))
def test_every_other_source_file_still_fails_on_post_or_body(label):
    others = [p for p in _source_files() if _rel(p) != NTFY_REL]
    assert others
    for path in others:
        text = path.read_text() + "\n" + _POST_LINES[label] + "\n"
        assert _violations(label, _rel(path), text), f"{_rel(path)} accepted {label}"


@pytest.mark.parametrize("line", ['URL = "/portfolio/orders"', "create_order(x)", "place_order(x)",
                                  "submit_order(x)", 'path = base + "/orders"', "client.post(url)",
                                  "session.put(url)", "import hmac", "sign_request(req)", "private_key = 1"])
def test_order_execution_patterns_stay_forbidden_in_the_notification_file(line):
    text = (SRC / NTFY_REL).read_text() + "\n" + line + "\n"
    assert any(_violations(label, NTFY_REL, text) for label in NEVER_EXEMPT), line


@pytest.mark.parametrize("label,line", [
    ("non-GET HTTP method", 'Request(url, method="PUT")'), ("non-GET HTTP method", "Request(url, method='patch')"),
    ("non-GET HTTP method", 'Request(url, method="DELETE")'), ("auth header", 'h["KALSHI-ACCESS-KEY"] = k'),
    ("auth header", "h['KALSHI-ACCESS-SIGNATURE'] = s"),
])
def test_the_notification_file_may_post_but_never_put_patch_delete_or_send_venue_headers(label, line):
    text = (SRC / NTFY_REL).read_text()
    assert not _violations(label, NTFY_REL, text)
    assert _violations(label, NTFY_REL, text + "\n" + line + "\n"), line


# Only the notification module may set its host allowlist or replace a sink's opener.
_ALLOWLIST_TAMPERING = re.compile(r"\b(SELF_HOSTED_HOSTS|DEFAULT_HOSTS)\b\s*(\+|\||-)?=(?!=)|\._opener\s*=(?!=)"
                                  r"|setattr\([^)]*[\"'](SELF_HOSTED_HOSTS|DEFAULT_HOSTS|_opener)[\"']")


def test_no_other_source_file_changes_the_ntfy_allowlist_or_opener():
    hits = [f"{_rel(p)}:{n}: {line.strip()}" for p in _source_files() if _rel(p) != NTFY_REL
            for n, line in enumerate(p.read_text().splitlines(), 1) if _ALLOWLIST_TAMPERING.search(line)]
    assert not hits, hits
    for probe in ("notify_ntfy.SELF_HOSTED_HOSTS = ('evil.example',)", "ntfy.DEFAULT_HOSTS += ('x',)",
                  "sink._opener = my_opener", 'setattr(notify_ntfy, "SELF_HOSTED_HOSTS", ("x",))'):
        assert _ALLOWLIST_TAMPERING.search(probe), probe


# Venue, data-source and trading words that must never appear in the notification file. Its
# hosts come from a fixed allowlist of ntfy hosts, so it needs none of them.
_VENUE_TEXT = re.compile(r"kalshi|polymarket|novig|odds[-_ ]?api|the-odds|pinnacle|betfair|draftkings|fanduel"
                         r"|/orders|\borders?\b|create_order|place_order|trade-api|portfolio|balance|withdraw"
                         r"|deposit|https?://", re.I)


def test_the_notification_file_names_no_venue_host_order_path_or_url():
    text = (SRC / NTFY_REL).read_text()
    hits = [f"{lineno}: {line.strip()}" for lineno, line in enumerate(text.splitlines(), 1)
            if _VENUE_TEXT.search(line)]
    assert not hits, "the notification file may name only allowlisted ntfy hosts, never a venue:\n" + "\n".join(hits)


def test_the_notification_file_imports_nothing_that_can_trade():
    import ast

    tree = ast.parse((SRC / NTFY_REL).read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add("." * node.level + (node.module or ""))
    allowed = {"__future__", "hashlib", "http.client", "ipaddress", "json", "os", "re", "ssl", "time", "dataclasses",
               "datetime", "typing", "urllib.error", "urllib.parse", "urllib.request", ".freshness", ".notifications",
               ".redaction"}
    assert modules <= allowed, modules - allowed


def test_the_notification_host_allowlist_is_reviewed_code():
    """Publishing goes only to ntfy.sh. A self-hosted server is added here and in the module,
    in the same reviewed PR; configuration can never add a host."""
    from edge_lab import notify_ntfy

    assert notify_ntfy.DEFAULT_HOSTS == ("ntfy.sh",)
    assert notify_ntfy.SELF_HOSTED_HOSTS == ()


_TOPIC16 = "mel-alerts-0123456789"


@pytest.mark.parametrize("url", [
    "https://external-api.kalshi.com/{t}", "https://kalshi.com/orders", "https://gateway.polymarket.us/{t}",
    "https://polymarket.com/{t}", "https://data.novig.com/{t}", "https://api.the-odds-api.com/{t}",
    "https://api.betfair.com/{t}", "https://api.pinnacle.com/{t}", "https://www.predictit.org/{t}",
    "https://169.254.169.254/{t}", "https://127.0.0.1/{t}", "https://[::1]/{t}", "https://[fe80::1]/{t}",
    "https://ntfy.sh.evil.com/{t}", "https://evil.com/ntfy.sh", "https://evil.com/{t}?h=ntfy.sh",
    "https://user@ntfy.sh/{t}", "https://user:pass@ntfy.sh/{t}", "https://ntfy.sh@evil.com/{t}",
    "https://ntfy.sh:443@evil.com/{t}", "https://ntfy.sh:8443/{t}", "https://ntfy.sh:443/{t}", "https://ntfy.sh./{t}",
    "https://sub.ntfy.sh/{t}", "https://xntfy.sh/{t}", "http://ntfy.sh/{t}", "http://localhost/{t}",
    "ftp://ntfy.sh/{t}", "https://ntfy.sh/{t}/extra", "https://ntfy.sh/", "https://ntfy.sh/{t}?auth=x",
    "https://ntfy.sh/{t}#x", "https://ntfy.sh/to pic", "https://ntfy.sh/short-topic", "https://ntfy.sh/" + "a" * 65,
])
def test_the_notification_file_refuses_everything_but_an_allowlisted_topic(url):
    from edge_lab.notify_ntfy import NtfyConfigError, Target, parse_topic_url

    url = url.format(t=_TOPIC16)
    with pytest.raises(NtfyConfigError):
        parse_topic_url(url)
    with pytest.raises(NtfyConfigError):
        Target(url)  # building a Target directly validates too


def test_every_registered_source_host_is_refused_as_a_notification_target():
    from urllib.parse import urlsplit

    from edge_lab.notify_ntfy import NtfyConfigError, parse_topic_url
    from edge_lab.sources import REGISTRY

    for spec in REGISTRY.values():
        with pytest.raises(NtfyConfigError):
            parse_topic_url(f"https://{urlsplit(spec.base_url).hostname}/{_TOPIC16}")


def test_only_allowlisted_hosts_are_accepted(monkeypatch):
    from edge_lab import notify_ntfy

    assert notify_ntfy.parse_topic_url(f"https://ntfy.sh/{_TOPIC16}").url == f"https://ntfy.sh/{_TOPIC16}"
    assert notify_ntfy.parse_topic_url(f"https://NTFY.sh/{_TOPIC16}").host == "ntfy.sh"
    with pytest.raises(notify_ntfy.NtfyConfigError):
        notify_ntfy.parse_topic_url(f"https://ntfy.example.org/{_TOPIC16}")
    monkeypatch.setattr(notify_ntfy, "SELF_HOSTED_HOSTS", ("ntfy.example.org",))  # as a reviewed change would
    assert notify_ntfy.parse_topic_url(f"https://ntfy.example.org/{_TOPIC16}").host == "ntfy.example.org"


def test_http_client_only_issues_get():
    from conftest import ScriptedOpener
    from edge_lab.http import fetch

    opener = ScriptedOpener({"ok": True})
    fetch("https://example.test/x", opener=opener, sleep=lambda s: None)
    assert all(call.startswith("GET ") for call in opener.calls)


ROOT = SRC.parent


# The exact credentialed sources, each with an approval phrase that must appear verbatim in
# its owner approval file and in docs/EXECUTION_PLAN.md. Adding a credentialed source means
# changing this table in the same PR as the owner decision.
APPROVED_CREDENTIALS = {
    "the_odds_api": {
        "approval_phrase": "The Odds API FREE-tier adapter foundation",
        "plan_phrase": "the owner may install The Odds API free read-only key",
    },
    # The same key's quota-free schedule discovery, registered separately so its health is never
    # read as odds-feed health (PR #67 review). It is not a second credential: see the test below.
    "the_odds_api_discovery": {
        "approval_phrase": "The Odds API FREE-tier adapter foundation",
        "plan_phrase": "the owner may install The Odds API free read-only key",
    },
}


def test_the_discovery_source_shares_the_one_odds_api_key():
    from edge_lab.sources import get_source

    odds, discovery = get_source("the_odds_api"), get_source("the_odds_api_discovery")
    for field in ("credential_kind", "credential_env_var", "credential_transport", "owner_approval_ref",
                  "base_url", "status", "requires_credentials"):
        assert getattr(discovery, field) == getattr(odds, field), field
    assert discovery.collected_by == () and discovery.legacy_name != odds.legacy_name


def test_only_owner_approved_read_only_data_feed_credentials_exist():
    """Replaces "no registered source requires credentials" (ADR 0019 adapters addendum).

    A credential may exist only as a READ_ONLY_DATA_FEED key: sent as a query parameter
    (never a header), read from a named environment variable, never on an ACTIVE source
    until a later decision, and backed by an owner approval on file that names it."""
    from edge_lab.sources import REGISTRY, CredentialKind, SourceStatus

    credentialed = [s for s in REGISTRY.values() if s.requires_credentials or s.credential_kind is not CredentialKind.NONE]
    assert {s.source_id for s in credentialed} == set(APPROVED_CREDENTIALS)
    plan = (ROOT / "docs/EXECUTION_PLAN.md").read_text(encoding="utf-8")
    plan_flat = " ".join(plan.split())
    for spec in credentialed:
        assert spec.requires_credentials, spec.source_id
        assert spec.credential_kind is CredentialKind.READ_ONLY_DATA_FEED, spec.source_id
        assert spec.credential_transport == "query_param", spec.source_id
        assert spec.credential_env_var and re.fullmatch(r"EDGE_LAB_[A-Z0-9_]+", spec.credential_env_var), spec.source_id
        assert spec.status is not SourceStatus.ACTIVE, spec.source_id
        assert spec.owner_approval_ref, spec.source_id
        approval = ROOT / spec.owner_approval_ref
        assert approval.is_file(), f"{spec.source_id}: {spec.owner_approval_ref} does not exist"
        phrases = APPROVED_CREDENTIALS[spec.source_id]
        assert phrases["approval_phrase"] in approval.read_text(encoding="utf-8"), spec.source_id
        assert phrases["plan_phrase"] in plan_flat, spec.source_id
    for spec in REGISTRY.values():
        if spec not in credentialed:
            assert not (spec.credential_env_var or spec.credential_transport or spec.owner_approval_ref), spec.source_id


def test_no_trading_credential_kind_exists():
    from edge_lab.sources import CredentialKind

    assert {k.name for k in CredentialKind} == {"NONE", "READ_ONLY_DATA_FEED"}


_ENV_READ = re.compile(r"""\bos\.(?:environ\b(?:\.get)?|getenv)\s*[\[(]\s*(?P<arg>[^\]),]*)""")
_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|COOKIE|SESSION", re.I)


_ENV_IMPORT = re.compile(r"\bfrom\s+os\s+import\b[^#\n]*\b(getenv|environ|environb|getenvb)\b|\bimport\s+os\s+as\b"
                         r"|\bos\.(environb|getenvb)\b|\b__import__\(\s*[\"']os")


def test_source_reads_no_secret_environment_variable_except_registered_credentials():
    from edge_lab.sources import REGISTRY

    registered = {s.credential_env_var for s in REGISTRY.values() if s.credential_env_var}
    literal_secret_reads, dynamic_reads, aliased = [], [], []
    for path in _source_files():
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            where = f"{path.relative_to(SRC)}:{lineno}"
            if _ENV_IMPORT.search(line):
                aliased.append(f"{where}: {line.strip()}")  # would hide reads from this scan
            if "os.environ" not in line and "getenv" not in line:
                continue
            matches = list(_ENV_READ.finditer(line))
            for m in matches:
                arg = m.group("arg").strip()
                literal = re.fullmatch(r"""["']([A-Za-z0-9_]+)["']""", arg)
                if literal is None:
                    dynamic_reads.append(where)
                elif _SECRET_NAME.search(literal.group(1)) and literal.group(1) not in registered:
                    literal_secret_reads.append(f"{where}: {literal.group(1)}")
            if not matches and "os.environ if environ is None" not in line:
                dynamic_reads.append(where)  # whole-environment access, or a bare getenv
    assert not aliased, aliased
    assert not literal_secret_reads, literal_secret_reads
    # The only non-literal read is odds_api.load_key, which reads the registered variable.
    assert all(w.startswith("edge_lab/odds_api.py:") for w in dynamic_reads), dynamic_reads


def test_the_notification_token_is_read_only_by_the_notification_file():
    """ADR 0022: `EDGE_LAB_NTFY_TOKEN` is an optional publish token for one ntfy topic, not a
    data-feed or trading credential. It is read through an injectable mapping in exactly one
    file, sent only as that file's Bearer header, and never logged."""
    users = [_rel(p) for p in _source_files() if "EDGE_LAB_NTFY_TOKEN" in p.read_text()]
    assert users == [NTFY_REL], users
    text = (SRC / NTFY_REL).read_text()
    assert "os.environ[" not in text and "os.getenv" not in text and "os.environ.get" not in text
    assert set(re.findall(r"\benv\.get\((\w+)\)", text)) == {"ENV_TOPIC_URL", "ENV_TOKEN"}
    assert len(re.findall(r"\benv\b[.\[]", text)) == 2  # no other lookup through the mapping


@pytest.mark.parametrize("header", ["Authorization", "Cookie", "X-Api-Key", "KALSHI-ACCESS-SIGNATURE", "X-Auth-Token"])
def test_http_client_refuses_credential_headers(header):
    from conftest import ScriptedOpener
    from edge_lab.http import fetch

    opener = ScriptedOpener({"ok": True})
    with pytest.raises(ValueError):
        fetch("https://example.test/x", headers={header: "x"}, opener=opener, sleep=lambda s: None)
    assert opener.calls == []
