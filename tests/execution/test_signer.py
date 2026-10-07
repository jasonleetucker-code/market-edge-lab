"""Kalshi request signer (#160 package F). Keys are generated at test time, never stored, never read from disk or
the environment. Signatures are verified with the generated key's public half."""

from __future__ import annotations

import base64
import copy
import pickle
from decimal import Decimal

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

from edge_lab.execution import kalshi_wire as w
from edge_lab.execution import signer as s
from edge_lab.execution.model import AccountScope, Environment

FIXTURE = Environment.FIXTURE
SCOPE = AccountScope(FIXTURE, "fixture-acct")
TS = 1791385230750  # 2026-10-07T15:00:30.750Z in milliseconds
KEY_ID = "fixture-key-id"


@pytest.fixture(scope="module")
def ed_key():
    return ed25519.Ed25519PrivateKey.generate()


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make(key, **kw):
    args = dict(key_id=KEY_ID, private_key=key, environment=FIXTURE, account_ref="fixture-acct")
    args.update(kw)
    return s.Signer(**args)


def pem(key, fmt=serialization.PrivateFormat.PKCS8, password=None) -> bytes:
    enc = serialization.NoEncryption() if password is None else serialization.BestAvailableEncryption(password)
    return key.private_bytes(serialization.Encoding.PEM, fmt, enc)


def verify(signer, auth, text):
    raw = base64.b64decode(auth.signature, validate=True)
    if signer.algorithm is s.KeyAlgorithm.ED25519:
        signer.public_key().verify(raw, text.encode("utf-8"))
    else:
        signer.public_key().verify(raw, text.encode("utf-8"),
                                   padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())


BALANCE = w.build_get_balance(SCOPE)
ORDERS = w.build_get_orders(SCOPE, limit=5)
CANCEL = w.build_cancel(SCOPE, "3b23c1c7-f4ef-4f0d-8b9a-9e53c61f1a0d", exchange_index=0)


def test_the_presign_text_is_timestamp_method_and_full_path_without_query():
    assert s.Signer.presign_text(BALANCE, TS) == f"{TS}GET/trade-api/v2/portfolio/balance"
    assert ORDERS.query  # the query is not signed (AUTH-05)
    assert s.Signer.presign_text(ORDERS, TS) == f"{TS}GET/trade-api/v2/portfolio/orders"
    assert s.Signer.presign_text(CANCEL, TS) == \
        f"{TS}DELETE/trade-api/v2/portfolio/events/orders/3b23c1c7-f4ef-4f0d-8b9a-9e53c61f1a0d"
    facts = {f.id: f for f in s.SIGNING_FACTS}
    example = facts["AUTH-07"].value  # the documented example has the same shape
    assert example == s.Signer.presign_text(BALANCE, 1703123456789)


@pytest.mark.parametrize("key_name", ["ed_key", "rsa_key"])
@pytest.mark.parametrize("request_", [BALANCE, ORDERS, CANCEL], ids=["balance", "orders-with-query", "cancel"])
def test_signatures_verify_with_the_public_key(request, key_name, request_):
    signer = make(request.getfixturevalue(key_name))
    auth = signer.sign(request_, timestamp_ms=TS)
    assert auth.key_id == KEY_ID and auth.timestamp_ms == str(TS)
    verify(signer, auth, s.Signer.presign_text(request_, TS))
    with pytest.raises(InvalidSignature):  # a different path or timestamp does not verify
        verify(signer, auth, s.Signer.presign_text(BALANCE if request_ is not BALANCE else ORDERS, TS))
    with pytest.raises(InvalidSignature):
        verify(signer, auth, s.Signer.presign_text(request_, TS + 1))


def test_the_algorithm_comes_from_the_parsed_key(ed_key, rsa_key):
    assert make(ed_key).algorithm is s.KeyAlgorithm.ED25519
    assert make(rsa_key).algorithm is s.KeyAlgorithm.RSA_PSS_SHA256
    # an RSA key in PKCS#8 has the same generic label an Ed25519 key has (AUTH-04)
    rsa_pkcs8 = pem(rsa_key)
    assert rsa_pkcs8.splitlines()[0] == pem(ed_key).splitlines()[0]
    assert s.Signer.from_pem(rsa_pkcs8, key_id=KEY_ID, environment=FIXTURE,
                             account_ref="fixture-acct").algorithm is s.KeyAlgorithm.RSA_PSS_SHA256
    rsa_pkcs1 = pem(rsa_key, serialization.PrivateFormat.TraditionalOpenSSL)
    assert s.Signer.from_pem(rsa_pkcs1, key_id=KEY_ID, environment=FIXTURE,
                             account_ref="fixture-acct").algorithm is s.KeyAlgorithm.RSA_PSS_SHA256


def test_a_pem_labelled_as_one_type_but_holding_another_is_never_taken_at_its_label(ed_key):
    relabelled = pem(ed_key).replace(b"BEGIN PRIVATE", b"BEGIN RSA PRIVATE").replace(b"END PRIVATE", b"END RSA PRIVATE")
    try:
        signer = s.Signer.from_pem(relabelled, key_id=KEY_ID, environment=FIXTURE, account_ref="fixture-acct")
    except s.KeyLoadError:
        return  # refused: the body is not the PKCS#1 RSA structure its label claims
    assert signer.algorithm is s.KeyAlgorithm.ED25519  # if parsed at all, the parsed type decides


def test_rsa_pss_signatures_are_randomised_but_ed25519_is_deterministic(ed_key, rsa_key):
    ed = make(ed_key)
    assert ed.sign(BALANCE, timestamp_ms=TS).signature == ed.sign(BALANCE, timestamp_ms=TS).signature
    r = make(rsa_key)
    assert r.sign(BALANCE, timestamp_ms=TS).signature != r.sign(BALANCE, timestamp_ms=TS).signature
    assert len(base64.b64decode(ed.sign(BALANCE, timestamp_ms=TS).signature)) == 64


def test_encrypted_pem_needs_its_password(ed_key):
    data = pem(ed_key, password=b"pw")
    assert s.Signer.from_pem(data, key_id=KEY_ID, environment=FIXTURE, account_ref="fixture-acct",
                             password=b"pw").algorithm is s.KeyAlgorithm.ED25519
    for password in (None, b"wrong"):
        with pytest.raises(s.KeyLoadError):
            s.Signer.from_pem(data, key_id=KEY_ID, environment=FIXTURE, account_ref="fixture-acct", password=password)


@pytest.mark.parametrize("bad", [b"", b"not a key", b"-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----\n",
                                 "a str, not bytes"])
def test_an_invalid_pem_is_refused_without_echoing_it(bad):
    with pytest.raises(s.KeyLoadError) as info:
        s.Signer.from_pem(bad, key_id=KEY_ID, environment=FIXTURE, account_ref="fixture-acct")
    assert info.value.__cause__ is None and (info.value.__context__ is None or info.value.__suppress_context__)
    if isinstance(bad, bytes) and bad:
        assert bad.decode(errors="ignore")[:12] not in str(info.value)


def test_wrong_key_types_are_refused(ed_key):
    for key in (ec.generate_private_key(ec.SECP256R1()), ed_key.public_key(),
                rsa.generate_private_key(public_exponent=65537, key_size=1024), b"raw bytes", None):
        with pytest.raises(s.UnsupportedKeyError):
            make(key)
    with pytest.raises(s.UnsupportedKeyError):
        s.Signer.from_pem(pem(ec.generate_private_key(ec.SECP256R1())), key_id=KEY_ID, environment=FIXTURE,
                          account_ref="fixture-acct")


@pytest.mark.parametrize("env", [Environment.DEMO, Environment.PRODUCTION, "FIXTURE"])
def test_no_signer_exists_outside_authorized_environments_even_with_a_valid_key(ed_key, env):
    with pytest.raises(s.SigningRefused):
        make(ed_key, environment=env)


@pytest.mark.parametrize("ts", [1791385230, 1791385230750000, -1, 0, True, 1791385230750.0, "1791385230750",
                                Decimal("1791385230750")])
def test_timestamps_must_be_integer_milliseconds(ed_key, ts):
    with pytest.raises(s.SigningRefused):
        make(ed_key).sign(BALANCE, timestamp_ms=ts)


def test_only_allowlisted_wire_requests_for_this_account_are_signed(ed_key):
    signer = make(ed_key)
    for bad in ("/trade-api/v2/portfolio/balance", {"endpoint": "GET_BALANCE"}, None):
        with pytest.raises(ValueError):
            signer.sign(bad, timestamp_ms=TS)
    other_account = w.build_get_balance(AccountScope(FIXTURE, "other-acct"))
    with pytest.raises(s.SigningRefused):
        signer.sign(other_account, timestamp_ms=TS)
    other_env = w.build_get_balance(AccountScope(Environment.PRODUCTION, "fixture-acct"))
    with pytest.raises(s.SigningRefused):
        signer.sign(other_env, timestamp_ms=TS)
    tampered = object.__new__(w.WireRequest)  # bypassing __init__ does not bypass the re-check
    for name, value in (("endpoint", w.Endpoint.GET_BALANCE), ("scope", SCOPE), ("path", "/portfolio/../admin"),
                        ("query", ()), ("body", None), ("exchange_index", None)):
        object.__setattr__(tampered, name, value)
    with pytest.raises(ValueError):
        signer.sign(tampered, timestamp_ms=TS)
    assert not any(hasattr(signer, name) for name in ("sign_text", "sign_bytes", "sign_message", "raw_sign"))


@pytest.mark.parametrize("key_name", ["ed_key", "rsa_key"])
def test_the_key_never_leaks_through_repr_pickle_copy_or_attributes(request, key_name):
    key = request.getfixturevalue(key_name)
    signer = make(key)
    secret = pem(key)
    auth = signer.sign(BALANCE, timestamp_ms=TS)
    for text in (repr(signer), str(signer), repr(auth), str(auth), f"{signer!r} {auth!r}"):
        assert KEY_ID not in text and auth.signature not in text and "BEGIN" not in text
    for attempt in (lambda: pickle.dumps(signer), lambda: copy.copy(signer), lambda: copy.deepcopy(signer),
                    lambda: pickle.dumps(auth)):
        with pytest.raises(TypeError):
            attempt()
    with pytest.raises(AttributeError):
        signer.extra = 1
    with pytest.raises(AttributeError):
        signer.__dict__  # slots only: no attribute bag to dump
    public_names = [n for n in dir(signer) if not n.startswith("_")]
    assert sorted(public_names) == ["account_ref", "algorithm", "environment", "from_pem", "presign_text",
                                    "public_key", "sign"]
    assert not isinstance(signer.public_key(), (ed25519.Ed25519PrivateKey, rsa.RSAPrivateKey))
    assert secret.splitlines()[1].decode() not in repr(signer)


def test_signer_errors_never_carry_key_material(ed_key):
    data = pem(ed_key)
    with pytest.raises(s.KeyLoadError) as info:
        s.Signer.from_pem(data[:-40], key_id=KEY_ID, environment=FIXTURE, account_ref="fixture-acct")
    for line in data.splitlines()[1:-1]:
        assert line.decode() not in str(info.value)
    with pytest.raises(s.SigningRefused) as refused:
        make(ed_key, key_id="has space")
    assert "has space" not in str(refused.value)
