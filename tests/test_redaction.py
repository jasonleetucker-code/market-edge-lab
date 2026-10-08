"""The shared secret patterns (`edge_lab.redaction`): each bypass found in the review of the execution status export
(#160 UI journeys, M1) is redacted by `redact_text` and refused by `contains_secret`; identifiers stay."""

from __future__ import annotations

import pytest

from edge_lab import redaction as r

KEY_BODY = "MC4CAQAwBQYDK2VwBCIEIGx0Zm9yZXZlcmFuZGV2ZXJhbmRldmVyYW5k"  # a base64 key-shaped run (not a real key)
PEM_HEAD = "-----BEGIN " + "OPENSSH " + "PRIVATE KEY-----"  # split so the repository secret scan does not flag it


@pytest.mark.parametrize("text", [
    "KALSHI-ACCESS-KEY: 0b5f0c33-aaaa-bbbb-cccc-1234567890ab",
    "kalshi-access-signature: c2lnbmF0dXJlYnl0ZXNoZXJl",
    "KALSHI-ACCESS-TIMESTAMP=1696700000000",
    "Authorization: Basic dXNlcjpwYXNzd29yZA==",
    "authorization: Bearer abc.def.ghi",
    "Proxy-Authorization: Basic Zm9vOmJhcg==",
    "X-Api-Key: abcdefghijklmnopq",
    "basic dXNlcjpwYXNzd29yZA==",
    "private_key=abcdefgh",
    "private-key: abcdefgh",
    "privatekey=abcdefgh",
    "client_secret=abcdefgh",
    "signature=c2lnbmF0dXJl",
    f"key body {KEY_BODY}",
    f"{KEY_BODY}==",
    "first line\nKALSHI-ACCESS-SIGNATURE: c2lnbmF0dXJl",
    PEM_HEAD,
])
def test_each_reviewed_bypass_is_refused_and_redacted(text):
    assert r.contains_secret(text), text
    redacted = r.redact_text(text)
    assert r.REDACTED in redacted
    assert not r.contains_secret(redacted.replace("=" + r.REDACTED, "").replace(": " + r.REDACTED, "")), redacted


@pytest.mark.parametrize("text", [
    "a" * 64,  # a SHA-256 hex digest is an identifier
    "11b31587223ce86ba715bb861d3141e41a880afb790cc6ae0bdbc9cb48f43788",
    "f87ed96a-2eee-581c-928b-4172f4a6cadc#1",
    "KXHIGHNY-26OCT08-B72",
    "reconciliation-lost:20261007T1507000000",
    "RECONCILIATION_NOT_COMPLETE: FAILED; INCIDENTS_NOT_ACKNOWLEDGED",
    "the signature of the grant is its digest",
    "Basic research, not advice",
    "2026-10-07T15:06:00+00:00",
])
def test_identifiers_and_ordinary_text_are_not_secrets(text):
    assert not r.contains_secret(text), text
    assert r.redact_text(text) == text


def test_the_header_value_is_redacted_to_the_end_of_its_line_only():
    out = r.redact_text("KALSHI-ACCESS-KEY: abc def\nnext line stays")
    assert out == "KALSHI-ACCESS-KEY=REDACTED\nnext line stays"
