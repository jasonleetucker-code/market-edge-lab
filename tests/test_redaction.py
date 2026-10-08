"""The shared secret patterns (`edge_lab.redaction`): each bypass found in the review of the execution status export
(#160 UI journeys, M1) is redacted by `redact_text` and refused by `contains_secret`; identifiers stay."""

from __future__ import annotations

import json

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
    "operator\npassword\n: hunter2",  # the name, a newline, then the separator (an operator_ref in #176's review)
    # Follow-ups to #176's review: narrowing the prose rules keeps every credential-shaped value.
    "KALSHI-ACCESS-KEY 0b5f0c33-aaaa-bbbb-cccc-1234567890ab",  # no separator: a key id, still redacted
    "x-api-key abcd1234efgh",
    "authorization: abc123def456",  # a bare token, no scheme
    "authorization: abc.def.ghijk",  # no digit, but token punctuation
    "authorization: abcdefghijklmnopqrs",  # letters only, but 16+ of them
    "Proxy-Authorization: Bearer abc.def.ghi",
    'Authorization: "Basic dXNlcjpwYXNzd29yZA=="',  # a quoted value
    'password="hunter2"',
    "signature: c2lnbmF0dXJl",
    f"{KEY_BODY[:30]}/{KEY_BODY[:30]}",  # a key body with a slash still has a digit
    "/".join(["MCowBQYDK2Vw"] * 4),
    "first\\nKALSHI-ACCESS-KEY: 0b5f0c33",  # after an encoded newline (JSON text): no word boundary before the name
    f"line\\n{KEY_BODY}",
])
def test_each_reviewed_bypass_is_refused_and_redacted(text):
    assert r.contains_secret(text), text
    redacted = r.redact_text(text)
    assert r.REDACTED in redacted
    assert not r.contains_secret(redacted.replace("=" + r.REDACTED, "").replace(": " + r.REDACTED, "")), redacted


@pytest.mark.parametrize("text", [
    "a" * 64,  # a SHA-256 hex digest is an identifier
    "11b31587223ce86ba715bb861d3141e41a880afb790cc6ae0bdbc9cb48f43788",
    "0fd636d2c6b1a3e4f5a6b7c8d9e0f1a2b3c4d5e6",  # a git SHA
    "f87ed96a-2eee-581c-928b-4172f4a6cadc#1",
    "KXHIGHNY-26OCT08-B72",
    "reconciliation-lost:20261007T1507000000",
    "RECONCILIATION_NOT_COMPLETE: FAILED; INCIDENTS_NOT_ACKNOWLEDGED",
    "the signature of the grant is its digest",
    "Basic research, not advice",
    "2026-10-07T15:06:00+00:00",
    # Follow-ups to #176's review: identifiers and prose the bare-base64 and name rules over-matched.
    "0x52908400098527886E0F7030069857D2E4169EE7",  # an EVM wallet address ('x' is a base64 letter)
    "0xdd22c2a0ea8b7c06a6f3d0e1c0f5ab6ffe5d6b8a7c3e2f1d0c9b8a7f6e5d4c3b",  # a Polymarket condition id
    "condition 0xdd22c2a0ea8b7c06a6f3d0e1c0f5ab6ffe5d6b8a7c3e2f1d0c9b8a7f6e5d4c3b resolved",
    "participation authorization: none",
    "authorization: required before any order",
    "the signature: missing…",
    "signature: unchecked",
    "docs/strategy/kalshi/execution/ledger/archive/notes",  # letters and slashes only: a path
    "see the KALSHI-ACCESS-KEY header",
])
def test_identifiers_and_ordinary_text_are_not_secrets(text):
    assert not r.contains_secret(text), text
    assert r.redact_text(text) == text


def test_the_header_value_is_redacted_to_the_end_of_its_line_only():
    out = r.redact_text("KALSHI-ACCESS-KEY: abc def\nnext line stays")
    assert out == "KALSHI-ACCESS-KEY=REDACTED\nnext line stays"


@pytest.mark.parametrize("text", [
    "operator authorization: Basic dXNlcjpwYXNzd29yZA== trailing",
    "KALSHI-ACCESS-SIGNATURE: c2lnbmF0dXJl \"quoted\" rest",
    "first\nKALSHI-ACCESS-KEY: 0b5f0c33\\more\nlast",
    'password: x"y" z',
    "private_key=ab\\cd\"e",
    'token="quoted-value"',
    f"body {KEY_BODY}",
    f"line\n{KEY_BODY}",  # encoded as "line\\n<body>": the run must not start on the escape's letter
])
def test_redacting_json_text_keeps_it_valid_json(text):
    """A value stops at a JSON string boundary and never splits an escape: `odds_api.save_snapshot` redacts
    `json.dumps` output and parses it back (#176 review)."""
    encoded = json.dumps({"a": text, "b": "after"}, sort_keys=True)
    decoded = json.loads(r.redact_text(encoded))  # parses
    assert decoded["b"] == "after" and r.REDACTED in decoded["a"]
    for leaked in ("dXNlcjpwYXNzd29yZA", "c2lnbmF0dXJl", "0b5f0c33", "ab\\cd", "quoted-value", KEY_BODY):
        assert leaked not in decoded["a"], decoded
