"""Content hashing and structural fingerprints for raw evidence.

Raw payloads are hashed over a canonical JSON encoding so the same content
always produces the same digest regardless of key order. A separate *shape*
fingerprint hashes only the structure (key paths and value types), which lets
us detect upstream schema changes without diffing values.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bytes_sha256(body: bytes) -> str:
    """Digest of the exact bytes received, before any JSON decoding."""
    return hashlib.sha256(body).hexdigest()


def payload_sha256(payload: Any) -> str:
    return sha256_hex(canonical_json(payload))


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _collect_shape(value: Any, path: str, out: set[str]) -> None:
    out.add(f"{path}:{_type_name(value)}")
    if isinstance(value, dict):
        for key, child in value.items():
            _collect_shape(child, f"{path}.{key}", out)
    elif isinstance(value, list):
        # Arrays contribute the union of their element shapes, so a list of 3
        # markets and a list of 30 markets with the same fields share a shape.
        for child in value:
            _collect_shape(child, f"{path}[]", out)


def shape_paths(payload: Any) -> list[str]:
    """Sorted `path:type` entries describing the payload's structure."""
    out: set[str] = set()
    _collect_shape(payload, "$", out)
    return sorted(out)


def shape_fingerprint(payload: Any) -> str:
    """SHA-256 of the payload's structure, ignoring all values."""
    return sha256_hex("\n".join(shape_paths(payload)))
