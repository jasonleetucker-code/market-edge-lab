"""The redaction regression corpus (#176 follow-up review): every string, raw and as JSON-escaped text, against a
frozen table of what `redact_text` returns now and whether `main` (5c7657e) redacted it.

Hard rule: a string main redacted is still redacted, unless it is one of the intended passes (prose values of
authorization/signature, an EVM address or bare 0x + 64 hex id, a letters-and-slashes path). Regenerate the table
only on purpose, and review every changed row.
"""

from __future__ import annotations

import base64
import json
import random

import pytest

from edge_lab import redaction as r

KEY_BODY = ("MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7" + "VJTUt9Us8cKjMzEfYyjiWA4R4/M2bS1GB4t7NXp98C3SC6dVMv"
            "DuictGeurT8jNbvJZHtCSuYEvuNMoSfm76oqFvAp8Gy0iz5sxjZmSnXyCdPEovGhLa0VzMaQ8s+CLOyS56YyCFGeJZ")  # not a key
ETH_PK = "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318"  # a published example key, not a secret
GH_TOKEN = "ghp" + "_" + "abcdefghijklmnopqrstuvwxyzABCDEF0123"  # split so no scanner reads it as a token
PEM_HEAD = "-----BEGIN " + "RSA " + "PRIVATE KEY-----"  # split so the repository secret scan does not flag it
AWS_KEY_ID = "AKIA" + "IOSFODNN7EXAMPLE"  # AWS's documented example id, split for the same scan


def _corpus() -> list[str]:
    out = [
        # names
        "password=hunter2", 'password=Pa"ss1234word', 'password=ab"cdefgh1234', "password: x", "token=abc",
        "api_key=abc123", "secret=s3cr3t&x=1", "cookie: a=b; c=d", "session_id=abcd", "passwd=xyz",
        "access_token='abc123'", "client_secret=abc", "private_key=abcdefgh", "signing_key: zz",
        'secret_key=k"ey123456', "operator\npassword\n: hunter2", 'password="hunter2"',
        # authorization
        "Authorization: Bearer abc", "Authorization: abcdefgh", "Authorization: abc123", "Authorization: Token abcdefghij",
        "Authorization: Token deadbeefcafe", "authorization: secretpassword", "Authorization: hunter2",
        'Authorization: Digest username="jason", realm="x", nonce="dcd98b7102dd2f0e8b11d0f600bfb0c093", '
        'response="6629fae49393a05397450978507c4ef1"',
        "Authorization: Basic dXNlcjpwYXNzd29yZA==", "Authorization: Basic YWxhZGRpbjpvcGVuc2VzYW1l",
        "Proxy-Authorization: abcdefghijk", "authorization=REDACTED", "Authorization: Bearer REDACTED",
        'Authorization: "abc123de"', "Authorization:\n abc123def", "Authorization: Bearer\tabcdefghijkl",
        "Authorization: AWS4-HMAC-SHA256 Credential=" + AWS_KEY_ID + "/20130524/us-east-1/s3/aws4_request, "
        "SignedHeaders=host, Signature=fe5f80f77d5fa3beca038a248ff027d0445342fe2855ddc963176630326f1024",
        "Authorization: token " + GH_TOKEN, "authorization: abcd'efgh123", "authorization: none (see grant 12)",
        # signature
        "signature=abc", "signature: abcdefghij", "signature=abcdefg1", "signature: c2lnbmF0dXJl", "signature=Zm9v",
        "signature: abc1234", 'signature=sig"123456789', "signature=abcdefghijklmnop", "signature: missing-ish",
        # kalshi headers
        "KALSHI-ACCESS-KEY: abc", "KALSHI-ACCESS-KEY: abcdefgh", "KALSHI-ACCESS-KEY 0b5f0c33-aaaa-bbbb-cccc-1234567890ab",
        "KALSHI-ACCESS-KEY abcdefghijkl", "KALSHI-ACCESS-KEY\t12345678", 'KALSHI-ACCESS-SIGNATURE: ab"cd+/ef==',
        "KALSHI-ACCESS-SIGNATURE: " + KEY_BODY[:88], "KALSHI-ACCESS-TIMESTAMP: 1696000000000",
        "x-api-key: abcdef", "X-API-KEY abcdefghij", "x-api-key=abc\\def", 'KALSHI-ACCESS-KEY: "0b5f0c33-aaaa"',
        "KALSHI-ACCESS-KEY: abc\\ def ghi", "KALSHI-ACCESS-KEY: abc\ndef",
        # bearer / basic
        "Bearer abcdefgh", "bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc", "basic dXNlcjpw",
        # bare base64 and 0x hex
        KEY_BODY, "0x" + KEY_BODY[:60], "0xABCDEF" + "0123456789abcdef" * 3, "0x" + "ab" * 20 + "G", ETH_PK,
        "0x" + "Ab12" * 16, "key " + ETH_PK, "eth_private_key: " + ETH_PK, '"seed": "' + ETH_PK + '"',
        "mnemonic=" + ETH_PK, "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA",
        "abcdefghijklmnopqrstuvwxyz/ABCDEFGHIJKLMNOP/qrstuv", "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRstuvwxyz",
        "abcdefghij/klmnopqrst/uvwxyzABCD/EFGHIJKLMN==", "Zm9vYmFyYmF6cXV4cXV1eHF1dXhxdXV4cXV1eHF1dXg=",
        "é" + KEY_BODY, "\t" + KEY_BODY[:40], "\b" + KEY_BODY, "\n" + KEY_BODY, "\\\\" + KEY_BODY,
        "xéMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIB", "u" + KEY_BODY,
        PEM_HEAD,
        "a\nKALSHI-ACCESS-KEY: 0b5f", "x\npassword=foo", "x\tsignature: c2lnbmF0dXJl",
        # urls
        "https://x.test/?apiKey=abc&x=1", "https://x.test/?token=abc",
        # ordinary text and identifiers
        "participation authorization: none", "authorization: required.", "Authorization: N/A",
        "the signature: missing", "the signature: missing.", "the signature: missing…", "signature: unchecked",
        "docs/strategy/kalshi/execution/ledger/archive/notes", "0x52908400098527886E0F7030069857D2E4169EE7",
        "0xdd22c2a0ea8b7c06a6f3d0e1c0f5ab6ffe5d6b8a7c3e2f1d0c9b8a7f6e5d4c3b", "see the KALSHI-ACCESS-KEY header",
        "11b31587223ce86ba715bb861d3141e41a880afb790cc6ae0bdbc9cb48f43788", "KXHIGHNY-26OCT08-B72",
        "the signature of the grant is its digest", "Basic research, not advice",
    ]
    rnd = random.Random(7)  # random base64 secrets of 40, 44 and 64 characters
    for n in (30, 32, 48):
        for _ in range(3):
            out.append(base64.b64encode(rnd.randbytes(n)).decode())
    return out


CORPUS = _corpus()
# Strings main redacted that are now kept on purpose (raw form; their JSON-escaped forms equal them).
INTENDED_PASSES = {
    "participation authorization: none", "authorization: required.", "Authorization: N/A",
    "the signature: missing", "the signature: missing.", "the signature: missing…", "signature: unchecked",
    "docs/strategy/kalshi/execution/ledger/archive/notes", "abcdefghijklmnopqrstuvwxyz/ABCDEFGHIJKLMNOP/qrstuv",
    "0x52908400098527886E0F7030069857D2E4169EE7", "0xdd22c2a0ea8b7c06a6f3d0e1c0f5ab6ffe5d6b8a7c3e2f1d0c9b8a7f6e5d4c3b",
    "0x" + "Ab12" * 16, ETH_PK,  # a bare 0x + 64 hex: indistinguishable from a condition id (module docstring)
}


def _cases() -> list[tuple[str, str, str]]:
    return [(f"{i:03d}-{form}", form, text if form == "raw" else json.dumps(text)[1:-1])
            for i, text in enumerate(CORPUS) for form in ("raw", "json")]


# id -> (main redacted it, contains_secret now, what redact_text returns now). Frozen; generated, then reviewed.
EXPECTED: dict[str, tuple[bool, bool, str]] = {
    '000-raw': (True, True, 'password=REDACTED'),
    '000-json': (True, True, 'password=REDACTED'),
    '001-raw': (True, True, 'password=REDACTED'),
    '001-json': (True, True, 'password=REDACTED'),
    '002-raw': (True, True, 'password=REDACTED'),
    '002-json': (True, True, 'password=REDACTED'),
    '003-raw': (True, True, 'password=REDACTED'),
    '003-json': (True, True, 'password=REDACTED'),
    '004-raw': (True, True, 'token=REDACTED'),
    '004-json': (True, True, 'token=REDACTED'),
    '005-raw': (True, True, 'api_key=REDACTED'),
    '005-json': (True, True, 'api_key=REDACTED'),
    '006-raw': (True, True, 'secret=REDACTED&x=1'),
    '006-json': (True, True, 'secret=REDACTED&x=1'),
    '007-raw': (True, True, 'cookie=REDACTED c=d'),
    '007-json': (True, True, 'cookie=REDACTED c=d'),
    '008-raw': (True, True, 'session_id=REDACTED'),
    '008-json': (True, True, 'session_id=REDACTED'),
    '009-raw': (True, True, 'passwd=REDACTED'),
    '009-json': (True, True, 'passwd=REDACTED'),
    '010-raw': (True, True, 'access_token=REDACTED'),
    '010-json': (True, True, 'access_token=REDACTED'),
    '011-raw': (True, True, 'client_secret=REDACTED'),
    '011-json': (True, True, 'client_secret=REDACTED'),
    '012-raw': (True, True, 'private_key=REDACTED'),
    '012-json': (True, True, 'private_key=REDACTED'),
    '013-raw': (True, True, 'signing_key=REDACTED'),
    '013-json': (True, True, 'signing_key=REDACTED'),
    '014-raw': (True, True, 'secret_key=REDACTED'),
    '014-json': (True, True, 'secret_key=REDACTED'),
    '015-raw': (True, True, 'operator\npassword=REDACTED'),
    '015-json': (False, False, 'operator\\npassword\\n: hunter2'),
    '016-raw': (True, True, 'password=REDACTED'),
    '016-json': (True, True, 'password=REDACTED'),
    '017-raw': (True, True, 'Authorization=REDACTED'),
    '017-json': (True, True, 'Authorization=REDACTED'),
    '018-raw': (True, True, 'Authorization=REDACTED'),
    '018-json': (True, True, 'Authorization=REDACTED'),
    '019-raw': (True, True, 'Authorization=REDACTED'),
    '019-json': (True, True, 'Authorization=REDACTED'),
    '020-raw': (True, True, 'Authorization=REDACTED'),
    '020-json': (True, True, 'Authorization=REDACTED'),
    '021-raw': (True, True, 'Authorization=REDACTED'),
    '021-json': (True, True, 'Authorization=REDACTED'),
    '022-raw': (True, True, 'authorization=REDACTED'),
    '022-json': (True, True, 'authorization=REDACTED'),
    '023-raw': (True, True, 'Authorization=REDACTED'),
    '023-json': (True, True, 'Authorization=REDACTED'),
    '024-raw': (True, True, 'Authorization=REDACTED'),
    '024-json': (True, True, 'Authorization=REDACTED'),
    '025-raw': (True, True, 'Authorization=REDACTED'),
    '025-json': (True, True, 'Authorization=REDACTED'),
    '026-raw': (True, True, 'Authorization=REDACTED'),
    '026-json': (True, True, 'Authorization=REDACTED'),
    '027-raw': (True, True, 'Proxy-Authorization=REDACTED'),
    '027-json': (True, True, 'Proxy-Authorization=REDACTED'),
    '028-raw': (False, True, 'authorization=REDACTED'),
    '028-json': (False, True, 'authorization=REDACTED'),
    '029-raw': (True, True, 'Authorization=REDACTED'),
    '029-json': (True, True, 'Authorization=REDACTED'),
    '030-raw': (True, True, 'Authorization=REDACTED'),
    '030-json': (True, True, 'Authorization=REDACTED'),
    '031-raw': (True, True, 'Authorization=REDACTED'),
    '031-json': (True, True, 'Authorization=REDACTED'),
    '032-raw': (True, True, 'Authorization=REDACTED'),
    '032-json': (True, True, 'Authorization=REDACTED'),
    '033-raw': (True, True, 'Authorization=REDACTED'),
    '033-json': (True, True, 'Authorization=REDACTED'),
    '034-raw': (True, True, 'Authorization=REDACTED'),
    '034-json': (True, True, 'Authorization=REDACTED'),
    '035-raw': (True, True, 'authorization=REDACTED'),
    '035-json': (True, True, 'authorization=REDACTED'),
    '036-raw': (True, True, 'authorization=REDACTED'),
    '036-json': (True, True, 'authorization=REDACTED'),
    '037-raw': (True, True, 'signature=REDACTED'),
    '037-json': (True, True, 'signature=REDACTED'),
    '038-raw': (True, True, 'signature=REDACTED'),
    '038-json': (True, True, 'signature=REDACTED'),
    '039-raw': (True, True, 'signature=REDACTED'),
    '039-json': (True, True, 'signature=REDACTED'),
    '040-raw': (True, True, 'signature=REDACTED'),
    '040-json': (True, True, 'signature=REDACTED'),
    '041-raw': (True, True, 'signature=REDACTED'),
    '041-json': (True, True, 'signature=REDACTED'),
    '042-raw': (True, True, 'signature=REDACTED'),
    '042-json': (True, True, 'signature=REDACTED'),
    '043-raw': (True, True, 'signature=REDACTED'),
    '043-json': (True, True, 'signature=REDACTED'),
    '044-raw': (True, True, 'signature=REDACTED'),
    '044-json': (True, True, 'signature=REDACTED'),
    '045-raw': (True, True, 'signature=REDACTED'),
    '045-json': (True, True, 'signature=REDACTED'),
    '046-raw': (True, True, 'KALSHI-ACCESS-KEY=REDACTED'),
    '046-json': (True, True, 'KALSHI-ACCESS-KEY=REDACTED'),
    '047-raw': (True, True, 'KALSHI-ACCESS-KEY=REDACTED'),
    '047-json': (True, True, 'KALSHI-ACCESS-KEY=REDACTED'),
    '048-raw': (False, True, 'KALSHI-ACCESS-KEY=REDACTED'),
    '048-json': (False, True, 'KALSHI-ACCESS-KEY=REDACTED'),
    '049-raw': (False, False, 'KALSHI-ACCESS-KEY abcdefghijkl'),
    '049-json': (False, False, 'KALSHI-ACCESS-KEY abcdefghijkl'),
    '050-raw': (False, True, 'KALSHI-ACCESS-KEY=REDACTED'),
    '050-json': (False, False, 'KALSHI-ACCESS-KEY\\t12345678'),
    '051-raw': (True, True, 'KALSHI-ACCESS-SIGNATURE=REDACTED'),
    '051-json': (True, True, 'KALSHI-ACCESS-SIGNATURE=REDACTED'),
    '052-raw': (True, True, 'KALSHI-ACCESS-SIGNATURE=REDACTED'),
    '052-json': (True, True, 'KALSHI-ACCESS-SIGNATURE=REDACTED'),
    '053-raw': (True, True, 'KALSHI-ACCESS-TIMESTAMP=REDACTED'),
    '053-json': (True, True, 'KALSHI-ACCESS-TIMESTAMP=REDACTED'),
    '054-raw': (True, True, 'x-api-key=REDACTED'),
    '054-json': (True, True, 'x-api-key=REDACTED'),
    '055-raw': (False, False, 'X-API-KEY abcdefghij'),
    '055-json': (False, False, 'X-API-KEY abcdefghij'),
    '056-raw': (True, True, 'x-api-key=REDACTED'),
    '056-json': (True, True, 'x-api-key=REDACTED'),
    '057-raw': (True, True, 'KALSHI-ACCESS-KEY=REDACTED'),
    '057-json': (True, True, 'KALSHI-ACCESS-KEY=REDACTED'),
    '058-raw': (True, True, 'KALSHI-ACCESS-KEY=REDACTED'),
    '058-json': (True, True, 'KALSHI-ACCESS-KEY=REDACTED'),
    '059-raw': (True, True, 'KALSHI-ACCESS-KEY=REDACTED\ndef'),
    '059-json': (True, True, 'KALSHI-ACCESS-KEY=REDACTED'),
    '060-raw': (True, True, 'REDACTED'),
    '060-json': (True, True, 'REDACTED'),
    '061-raw': (True, True, 'REDACTED'),
    '061-json': (True, True, 'REDACTED'),
    '062-raw': (False, False, 'basic dXNlcjpw'),
    '062-json': (False, False, 'basic dXNlcjpw'),
    '063-raw': (True, True, 'REDACTED'),
    '063-json': (True, True, 'REDACTED'),
    '064-raw': (True, True, 'REDACTED'),
    '064-json': (True, True, 'REDACTED'),
    '065-raw': (True, True, 'REDACTED'),
    '065-json': (True, True, 'REDACTED'),
    '066-raw': (True, True, 'REDACTED'),
    '066-json': (True, True, 'REDACTED'),
    '067-raw': (True, False, '0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318'),
    '067-json': (True, False, '0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318'),
    '068-raw': (True, False, '0xAb12Ab12Ab12Ab12Ab12Ab12Ab12Ab12Ab12Ab12Ab12Ab12Ab12Ab12Ab12Ab12'),
    '068-json': (True, False, '0xAb12Ab12Ab12Ab12Ab12Ab12Ab12Ab12Ab12Ab12Ab12Ab12Ab12Ab12Ab12Ab12'),
    '069-raw': (True, True, 'key=REDACTED'),
    '069-json': (True, True, 'key=REDACTED'),
    '070-raw': (True, True, 'eth_private_key=REDACTED'),
    '070-json': (True, True, 'eth_private_key=REDACTED'),
    '071-raw': (True, True, '"seed=REDACTED"'),
    '071-json': (True, True, '\\"seed=REDACTED\\"'),
    '072-raw': (False, True, 'mnemonic=REDACTED'),
    '072-json': (False, True, 'mnemonic=REDACTED'),
    '073-raw': (True, True, 'REDACTED'),
    '073-json': (True, True, 'REDACTED'),
    '074-raw': (True, False, 'abcdefghijklmnopqrstuvwxyz/ABCDEFGHIJKLMNOP/qrstuv'),
    '074-json': (True, False, 'abcdefghijklmnopqrstuvwxyz/ABCDEFGHIJKLMNOP/qrstuv'),
    '075-raw': (True, True, 'REDACTED'),
    '075-json': (True, True, 'REDACTED'),
    '076-raw': (True, True, 'REDACTED'),
    '076-json': (True, True, 'REDACTED'),
    '077-raw': (True, True, 'REDACTED'),
    '077-json': (True, True, 'REDACTED'),
    '078-raw': (True, True, 'éREDACTED'),
    '078-json': (True, True, '\\REDACTED'),
    '079-raw': (True, True, '\tREDACTED'),
    '079-json': (True, True, '\\REDACTED'),
    '080-raw': (True, True, '\x08REDACTED'),
    '080-json': (True, True, '\\REDACTED'),
    '081-raw': (True, True, '\nREDACTED'),
    '081-json': (True, True, '\\REDACTED'),
    '082-raw': (True, True, '\\\\REDACTED'),
    '082-json': (True, True, '\\\\\\\\REDACTED'),
    '083-raw': (True, True, 'xéREDACTED'),
    '083-json': (True, True, 'x\\REDACTED'),
    '084-raw': (True, True, 'REDACTED'),
    '084-json': (True, True, 'REDACTED'),
    '085-raw': (True, True, 'REDACTED'),
    '085-json': (True, True, 'REDACTED'),
    '086-raw': (True, True, 'a\nKALSHI-ACCESS-KEY=REDACTED'),
    '086-json': (False, True, 'a\\nKALSHI-ACCESS-KEY=REDACTED'),
    '087-raw': (True, True, 'x\npassword=REDACTED'),
    '087-json': (False, True, 'x\\npassword=REDACTED'),
    '088-raw': (True, True, 'x\tsignature=REDACTED'),
    '088-json': (False, True, 'x\\tsignature=REDACTED'),
    '089-raw': (True, True, 'https://x.test/?apiKey=REDACTED&x=1'),
    '089-json': (True, True, 'https://x.test/?apiKey=REDACTED&x=1'),
    '090-raw': (True, True, 'https://x.test/?token=REDACTED'),
    '090-json': (True, True, 'https://x.test/?token=REDACTED'),
    '091-raw': (True, False, 'participation authorization: none'),
    '091-json': (True, False, 'participation authorization: none'),
    '092-raw': (True, False, 'authorization: required.'),
    '092-json': (True, False, 'authorization: required.'),
    '093-raw': (True, False, 'Authorization: N/A'),
    '093-json': (True, False, 'Authorization: N/A'),
    '094-raw': (True, False, 'the signature: missing'),
    '094-json': (True, False, 'the signature: missing'),
    '095-raw': (True, False, 'the signature: missing.'),
    '095-json': (True, False, 'the signature: missing.'),
    '096-raw': (True, False, 'the signature: missing…'),
    '096-json': (True, True, 'the signature=REDACTED'),
    '097-raw': (True, False, 'signature: unchecked'),
    '097-json': (True, False, 'signature: unchecked'),
    '098-raw': (True, False, 'docs/strategy/kalshi/execution/ledger/archive/notes'),
    '098-json': (True, False, 'docs/strategy/kalshi/execution/ledger/archive/notes'),
    '099-raw': (True, False, '0x52908400098527886E0F7030069857D2E4169EE7'),
    '099-json': (True, False, '0x52908400098527886E0F7030069857D2E4169EE7'),
    '100-raw': (True, False, '0xdd22c2a0ea8b7c06a6f3d0e1c0f5ab6ffe5d6b8a7c3e2f1d0c9b8a7f6e5d4c3b'),
    '100-json': (True, False, '0xdd22c2a0ea8b7c06a6f3d0e1c0f5ab6ffe5d6b8a7c3e2f1d0c9b8a7f6e5d4c3b'),
    '101-raw': (False, False, 'see the KALSHI-ACCESS-KEY header'),
    '101-json': (False, False, 'see the KALSHI-ACCESS-KEY header'),
    '102-raw': (False, False, '11b31587223ce86ba715bb861d3141e41a880afb790cc6ae0bdbc9cb48f43788'),
    '102-json': (False, False, '11b31587223ce86ba715bb861d3141e41a880afb790cc6ae0bdbc9cb48f43788'),
    '103-raw': (False, False, 'KXHIGHNY-26OCT08-B72'),
    '103-json': (False, False, 'KXHIGHNY-26OCT08-B72'),
    '104-raw': (False, False, 'the signature of the grant is its digest'),
    '104-json': (False, False, 'the signature of the grant is its digest'),
    '105-raw': (False, False, 'Basic research, not advice'),
    '105-json': (False, False, 'Basic research, not advice'),
    '106-raw': (True, True, 'REDACTED'),
    '106-json': (True, True, 'REDACTED'),
    '107-raw': (True, True, 'REDACTED'),
    '107-json': (True, True, 'REDACTED'),
    '108-raw': (True, True, 'REDACTED'),
    '108-json': (True, True, 'REDACTED'),
    '109-raw': (True, True, 'REDACTED'),
    '109-json': (True, True, 'REDACTED'),
    '110-raw': (True, True, 'REDACTED'),
    '110-json': (True, True, 'REDACTED'),
    '111-raw': (True, True, 'REDACTED'),
    '111-json': (True, True, 'REDACTED'),
    '112-raw': (True, True, 'REDACTED'),
    '112-json': (True, True, 'REDACTED'),
    '113-raw': (True, True, 'REDACTED'),
    '113-json': (True, True, 'REDACTED'),
    '114-raw': (True, True, 'REDACTED'),
    '114-json': (True, True, 'REDACTED'),
}


@pytest.mark.parametrize("case_id,form,text", _cases(), ids=[c[0] for c in _cases()])
def test_the_corpus_matches_its_frozen_table(case_id, form, text):
    main_redacted, refused, expected = EXPECTED[case_id]
    assert r.redact_text(text) == expected
    assert r.contains_secret(text) is refused
    assert refused or expected == text  # anything redacted is also refused
    raw = CORPUS[int(case_id[:3])]
    if main_redacted and raw not in INTENDED_PASSES:
        assert expected != text, f"main redacted {text!r}; it must still be redacted"


def test_the_table_covers_the_corpus_exactly():
    assert set(EXPECTED) == {c[0] for c in _cases()}
