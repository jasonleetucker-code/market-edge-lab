"""Kalshi request signer (#160 package F, ADR 0043). The only module that may import `cryptography`.

What it signs, exactly (AUTH-05, AUTH-06): the UTF-8 bytes of

    <timestamp in milliseconds> + <HTTP method, upper case> + <path from the host root, without the query>

for example `1703123456789GET/trade-api/v2/portfolio/balance`. The host and the query string are not signed.
The signature is standard base64.

- **Key type from the parsed key** (AUTH-04): an `Ed25519PrivateKey` signs the text directly (AUTH-02); an
  `RSAPrivateKey` signs with RSA-PSS, SHA-256, MGF1(SHA-256) and a salt as long as the digest (AUTH-03). The PEM
  label is never read: a PKCS#8 "PRIVATE KEY" block can hold either type.
- **No arbitrary signing.** `Signer.sign` accepts only a `kalshi_wire.WireRequest`, re-validated against the
  endpoint allowlist, for the signer's own environment and account.
- **The caller supplies the key** as PEM bytes or a parsed key object. Nothing here reads a file or an
  environment variable. The key is never returned, logged, printed, copied or pickled, and `repr` is redacted.
- **Only authorized environments.** A signer cannot be built for DEMO or PRODUCTION while
  `model.environment_authorized` refuses them, whatever key is supplied.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

from . import kalshi_wire
from .conformance import Evidence, Fact, Support
from .model import Environment, environment_authorized

_KEYS = "https://docs.kalshi.com/getting_started/api_keys"
_QUICK = "https://docs.kalshi.com/getting_started/quick_start_authenticated_requests"
_ENVS = "https://docs.kalshi.com/getting_started/api_environments"
_D = Evidence.DOCUMENTED

SIGNING_FACTS: tuple[Fact, ...] = (
    Fact("AUTH-01", ("Ed25519 (recommended)", "RSA 2048-bit"), _D, _KEYS),
    Fact("AUTH-02", "Ed25519 (RFC 8032) signs the pre-sign text directly", _D, _KEYS),
    Fact("AUTH-03", "RSA-PSS with SHA-256, MGF1 with SHA-256, salt length equal to the digest length", _D, _KEYS),
    Fact("AUTH-04", "the PEM header does not identify the key type; use the parsed key", _D, _KEYS),
    Fact("AUTH-05", "timestamp + METHOD + path from the API root, without the query; the host is not signed", _D,
         _ENVS),
    Fact("AUTH-06", "the signature is base64-encoded", _D, _KEYS),
    Fact("AUTH-07", "1703123456789GET/trade-api/v2/portfolio/balance", _D, _QUICK),  # example pre-sign text
    Fact("AUTH-08", "accepted clock skew for the timestamp", _D, _KEYS, support=Support.UNKNOWN),
    Fact("AUTH-09", "RSA key sizes other than 2048 bits", _D, _KEYS, support=Support.UNKNOWN),
)

# A plausible millisecond timestamp: 2020-09-13 to 2100-01-01. A seconds or microseconds value falls outside.
_MIN_TS_MS, _MAX_TS_MS = 1_600_000_000_000, 4_102_444_800_000
_RSA_MIN_BITS = 2048


class KeyAlgorithm(str, Enum):
    ED25519 = "ED25519"
    RSA_PSS_SHA256 = "RSA_PSS_SHA256"


class SignerError(Exception):
    """Base class. Messages never contain key material, signatures or request bodies."""


class KeyLoadError(SignerError):
    pass


class UnsupportedKeyError(SignerError):
    pass


class SigningRefused(SignerError):
    pass


@dataclass(frozen=True, repr=False)
class AuthValues:
    """The three values the transport sends as the venue's auth headers. `repr` is redacted."""

    key_id: str
    timestamp_ms: str
    signature: str

    def __repr__(self) -> str:
        return "AuthValues(<redacted>)"

    def __reduce__(self) -> Any:
        raise TypeError("auth values are not serializable")


def _algorithm(key: object) -> KeyAlgorithm:
    if isinstance(key, ed25519.Ed25519PrivateKey):
        return KeyAlgorithm.ED25519
    if isinstance(key, rsa.RSAPrivateKey):
        if key.key_size < _RSA_MIN_BITS:
            raise UnsupportedKeyError(f"RSA keys must be at least {_RSA_MIN_BITS} bits")
        return KeyAlgorithm.RSA_PSS_SHA256
    raise UnsupportedKeyError(f"unsupported key type {type(key).__name__}: Ed25519 or RSA private keys only")


def _sign_with(key: Any, algorithm: KeyAlgorithm) -> Callable[[bytes], bytes]:
    """A closure holding the key, so no attribute of the signer refers to it directly."""
    if algorithm is KeyAlgorithm.ED25519:
        return lambda message: key.sign(message)
    pss = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH)
    return lambda message: key.sign(message, pss, hashes.SHA256())


class Signer:
    """Signs allowlisted Kalshi requests for one environment and one account with one key."""

    __slots__ = ("_key_id", "_environment", "_account_ref", "_algorithm", "_sign", "_public")

    def __init__(self, *, key_id: str, private_key: object, environment: Environment, account_ref: str):
        if not isinstance(environment, Environment) or not environment_authorized(environment):
            raise SigningRefused("signing is not authorized in this environment")
        if not isinstance(key_id, str) or not key_id or not key_id.isprintable() or " " in key_id or len(key_id) > 128:
            raise SigningRefused("key_id must be a short printable identifier")
        if not isinstance(account_ref, str) or not account_ref:
            raise SigningRefused("account_ref is required")
        algorithm = _algorithm(private_key)
        object.__setattr__(self, "_key_id", key_id)
        object.__setattr__(self, "_environment", environment)
        object.__setattr__(self, "_account_ref", account_ref)
        object.__setattr__(self, "_algorithm", algorithm)
        object.__setattr__(self, "_sign", _sign_with(private_key, algorithm))
        object.__setattr__(self, "_public", private_key.public_key())  # type: ignore[attr-defined]

    @classmethod
    def from_pem(cls, pem: bytes, *, key_id: str, environment: Environment, account_ref: str,
                 password: bytes | None = None) -> "Signer":
        """Parse caller-supplied PEM bytes. Errors never echo the PEM."""
        if not isinstance(pem, (bytes, bytearray)):
            raise KeyLoadError("the PEM must be bytes")
        if password is not None and not isinstance(password, (bytes, bytearray)):
            raise KeyLoadError("the password must be bytes")
        try:
            key = serialization.load_pem_private_key(bytes(pem), password=None if password is None else bytes(password))
        except (ValueError, TypeError, UnsupportedAlgorithm):
            raise KeyLoadError("the PEM could not be parsed as a private key") from None
        return cls(key_id=key_id, private_key=key, environment=environment, account_ref=account_ref)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("a Signer is immutable")

    def __repr__(self) -> str:
        return f"Signer(<redacted>, algorithm={self._algorithm.value}, environment={self._environment.value})"

    __str__ = __repr__

    def __reduce_ex__(self, protocol: object) -> Any:
        raise TypeError("a Signer cannot be pickled or copied")

    def __copy__(self) -> Any:
        raise TypeError("a Signer cannot be copied")

    def __deepcopy__(self, memo: object) -> Any:
        raise TypeError("a Signer cannot be copied")

    @property
    def algorithm(self) -> KeyAlgorithm:
        return self._algorithm

    @property
    def environment(self) -> Environment:
        return self._environment

    @property
    def account_ref(self) -> str:
        return self._account_ref

    def public_key(self) -> Any:
        """The public half (not secret), e.g. for a test to verify a signature."""
        return self._public

    @staticmethod
    def presign_text(request: kalshi_wire.WireRequest, timestamp_ms: int) -> str:
        """The exact text that is signed for `request` at `timestamp_ms` (AUTH-05)."""
        kalshi_wire.check_allowlisted(request)
        return f"{_timestamp_text(timestamp_ms)}{request.method.value}{request.full_path}"

    def sign(self, request: kalshi_wire.WireRequest, *, timestamp_ms: int) -> AuthValues:
        kalshi_wire.check_allowlisted(request)
        if request.scope.environment is not self._environment or request.scope.account_ref != self._account_ref:
            raise SigningRefused("the request is for another environment or account")
        if not environment_authorized(self._environment):
            raise SigningRefused("signing is not authorized in this environment")
        text = self.presign_text(request, timestamp_ms)
        signature = base64.b64encode(self._sign(text.encode("utf-8"))).decode("ascii")
        return AuthValues(self._key_id, _timestamp_text(timestamp_ms), signature)


def _timestamp_text(timestamp_ms: int) -> str:
    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int):
        raise SigningRefused("the timestamp must be an integer number of milliseconds")
    if not _MIN_TS_MS <= timestamp_ms < _MAX_TS_MS:
        raise SigningRefused("the timestamp is not a plausible Unix time in milliseconds")
    return str(timestamp_ms)
