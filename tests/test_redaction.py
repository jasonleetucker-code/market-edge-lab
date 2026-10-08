"""The shared secret patterns (`edge_lab.redaction`): each bypass found in the reviews of the execution status export
(#160 UI journeys, M1) and of its follow-up is redacted by `redact_text` and refused by `contains_secret`; identifiers
and the documented prose values stay. The regression corpus against main is `test_redaction_corpus.py`."""

from __future__ import annotations

import json
import random

import pytest

from edge_lab import redaction as r

KEY_BODY = "MC4CAQAwBQYDK2VwBCIEIGx0Zm9yZXZlcmFuZGV2ZXJhbmRldmVyYW5k"  # a base64 key-shaped run (not a real key)
ETH_PK = "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318"  # a published example key
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
    # Follow-ups to #176's review. A value runs greedily to whitespace or '&', quotes included (MEDIUM 1).
    'password=Pa"ss1234word',
    'signature=sig"123456789',
    "authorization: abcd'efgh123",
    'password="hunter2"',
    'Authorization: Digest username="jason", realm="x", response="6629fae49393a05397450978507c4ef1"',
    # authorization and signature redact any value but a prose word (MEDIUM 2).
    "Authorization: hunter2",
    "Authorization: abc123",
    "Authorization: abcdefgh",
    "authorization: secretpassword",
    "Authorization: Token abcdefghij",
    "Proxy-Authorization: abcdefghijk",
    "Authorization: Bearer abc",
    "signature: abc1234",
    "signature: abcdefghij",
    "authorization: none (see grant 12)",  # a prose word is only a pass as the whole value
    "signature: missing-ish",
    # A Kalshi header or x-api-key with no separator, when the value is credential-like.
    "KALSHI-ACCESS-KEY 0b5f0c33-aaaa-bbbb-cccc-1234567890ab",
    "x-api-key abcd1234efgh",
    # 0x + 64 hex after a key-ish name is an EVM private key (LOW 1).
    "key " + ETH_PK,
    "eth_private_key: " + ETH_PK,
    "seed=" + ETH_PK,
    '"mnemonic": "' + ETH_PK + '"',
    # JSON-escaped text logged as raw text (LOW 2): escapes never hide a name or a key body.
    json.dumps("é" + KEY_BODY)[1:-1],
    json.dumps("Authorization: Bearer\tabcdefghijkl")[1:-1],
    json.dumps("Authorization:\n abc123def")[1:-1],
    "first\\nKALSHI-ACCESS-KEY: 0b5f0c33",
    f"line\\n{KEY_BODY}",
    f"{KEY_BODY[:30]}/{KEY_BODY[:30]}",  # a key body with a slash still has a digit
])
def test_each_reviewed_bypass_is_refused_and_redacted(text):
    assert r.contains_secret(text), text
    redacted = r.redact_text(text)
    assert r.REDACTED in redacted
    assert not r.contains_secret(redacted.replace("=" + r.REDACTED, "").replace(": " + r.REDACTED, "")), redacted


@pytest.mark.parametrize("text,leaked", [
    ('password=Pa"ss1234word', "ss1234word"),
    ('signature=sig"123456789', "123456789"),
    ("authorization: abcd'efgh123", "efgh123"),
    ('Authorization: Digest username="jason", response="6629fae49393a05397450978507c4ef1"', "6629fae4"),
])
def test_a_quote_inside_a_value_never_ends_redaction_early(text, leaked):
    assert leaked not in r.redact_text(text)


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
    "authorization: required.",  # trailing punctuation is ignored (LOW 4)
    "Authorization: N/A",
    "AUTHORIZATION: Pending",
    "the signature: missing",
    "the signature: missing.",
    "the signature: missing…",
    "signature: unchecked",
    "docs/strategy/kalshi/execution/ledger/archive/notes",  # letters and slashes only: a path
    "see the KALSHI-ACCESS-KEY header",
])
def test_identifiers_and_ordinary_text_are_not_secrets(text):
    assert not r.contains_secret(text), text
    assert r.redact_text(text) == text


def test_a_bare_0x_64_hex_value_is_kept_by_design():
    """Documented residual (module docstring): a bare 0x + 64 hex is indistinguishable from a condition id or a
    transaction hash, so it passes; the same value after a key-ish name is redacted."""
    assert r.redact_text(ETH_PK) == ETH_PK and not r.contains_secret(ETH_PK)
    assert r.redact_text("seed phrase " + ETH_PK) == "seed phrase " + ETH_PK  # a word between: not adjacent
    assert r.redact_text("secret key " + ETH_PK) == "secret key=REDACTED"
    assert r.redact_text("0x" + "ab" * 31) == "REDACTED"  # 0x + 62 hex is neither shape: a bare run, as on main


def test_the_header_value_is_redacted_to_the_end_of_its_line_only():
    out = r.redact_text("KALSHI-ACCESS-KEY: abc def\nnext line stays")
    assert out == "KALSHI-ACCESS-KEY=REDACTED\nnext line stays"


def test_structured_values_are_redacted_string_by_string():
    """`redact_json` redacts each string on its own (keys too), so the result always encodes to valid JSON; the
    dumped JSON text is never redacted as text (#176 review: odds_api.save_snapshot)."""
    value = {"note": 'operator authorization: Basic dXNlcjpwYXNzd29yZA== "quoted"', "n": [1, 2.5, None, True],
             "nested": {"private_key=abc": ("token=x\"y", "plain")}, 7: "seven", "error": ValueError("token=abc123")}
    out = r.redact_json(value)
    assert json.loads(json.dumps(out)) == out
    assert out["note"] == "operator authorization=REDACTED" and out["n"] == [1, 2.5, None, True]
    assert out["nested"] == {"private_key=REDACTED": ["token=REDACTED", "plain"]} and out["7"] == "seven"
    assert out["error"] == "token=REDACTED"  # any other leaf is redacted as its str()
    with pytest.raises(ValueError, match="same text"):
        r.redact_json({"token=a": 1, "token=b": 2})


FUZZ_TOKENS = ["password", "token", "api_key", "secret_key", "signature", "authorization", "Authorization",
               "KALSHI-ACCESS-KEY", "x-api-key", "bearer", "Bearer", "basic", ":", "=", " ", "\n", "\t", "\b", "\f",
               "\r", '"', "'", "\\", "\\n", "\\u", "é", "→", "\x00", "abc123def", "dXNlcjpwYXNzd29yZA==",
               KEY_BODY, "0x" + "ab" * 32, "/", "+", "&", "{", "}", '{"k": "v"}', json.dumps({"token": 'x"y'}),
               "hunter2", "abcdefgh12", "xyz", "none", "missing."]


def test_structured_redaction_always_encodes_to_valid_json():
    """LOW 3: the JSON-validity claim, proved for `redact_json` by a seeded, bounded fuzz (the reviewer's token set).
    `redact_text` over JSON text makes no such claim."""
    rnd = random.Random(20261008)
    for _ in range(3000):
        s = "".join(rnd.choice(FUZZ_TOKENS) for _ in range(rnd.randint(1, 8)))
        out = r.redact_json({"a": s, "b": "after", "n": [s, {"c": s}], "k" + s: s})
        for ensure_ascii in (True, False):
            assert json.loads(json.dumps(out, ensure_ascii=ensure_ascii)) == out
        assert out["b"] == "after" and out["a"] == out["n"][0] == out["n"][1]["c"] == r.redact_text(s)
