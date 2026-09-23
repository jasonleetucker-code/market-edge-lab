"""The repository cannot place orders or authenticate to a venue (gate 1-2 boundary).

If a future, owner-approved gate needs execution code, it goes in a separate
component with its own review, and this test changes in the same PR as that decision.
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


def _source_files():
    return sorted(SRC.rglob("*.py"))


def test_source_tree_is_scanned():
    assert _source_files(), "no source files found; scan would pass vacuously"


@pytest.mark.parametrize("label", sorted(FORBIDDEN))
def test_no_execution_or_auth_code(label):
    pattern = FORBIDDEN[label]
    hits = [
        f"{path.relative_to(SRC)}:{lineno}: {line.strip()}"
        for path in _source_files()
        for lineno, line in enumerate(path.read_text().splitlines(), 1)
        if pattern.search(line)
    ]
    assert not hits, f"{label} found:\n" + "\n".join(hits)


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
}


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


@pytest.mark.parametrize("header", ["Authorization", "Cookie", "X-Api-Key", "KALSHI-ACCESS-SIGNATURE", "X-Auth-Token"])
def test_http_client_refuses_credential_headers(header):
    from conftest import ScriptedOpener
    from edge_lab.http import fetch

    opener = ScriptedOpener({"ok": True})
    with pytest.raises(ValueError):
        fetch("https://example.test/x", headers={header: "x"}, opener=opener, sleep=lambda s: None)
    assert opener.calls == []
