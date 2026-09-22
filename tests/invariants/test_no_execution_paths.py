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


def test_no_registered_source_requires_credentials():
    from edge_lab.sources import REGISTRY

    assert not [s.source_id for s in REGISTRY.values() if s.requires_credentials]
