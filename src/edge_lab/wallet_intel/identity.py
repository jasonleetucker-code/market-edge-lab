"""Public pseudonymous account identity and time-versioned proxy mappings (W2, ADR 0045).

- An `AccountRef` is a public, pseudonymous identifier on one product: a venue or chain plus an
  address. It is never a person. There is no field for a real name, and heuristic clusters are
  labelled HEURISTIC, never verified.
- A `ProxyMapping` links a controlling account (an owner or signer) to a trading account (a proxy,
  deposit wallet or session signer). Polymarket documents that one signer can control several
  deposit wallets and that a wallet can grant scoped, time-limited signers
  (docs.polymarket.com/trading/wallets-auth, retrieved 2026-10-07), so mappings are many-to-many
  and time-versioned.
- Mappings are **bitemporal**: `valid_from`/`valid_to` say when the link held in the world, and
  `observed_at` says when we learned it. A query names both an event time and a knowledge time,
  so a link learned later never rewrites what an earlier decision could have known.
- The registry is append-only. A revocation is a new record; nothing is edited or removed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .timeutil import require_aware

_ADDRESS = re.compile(r"[A-Za-z0-9:_.-]{1,128}")


class IdentityBasis(str, Enum):
    SOURCE_FIELD = "SOURCE_FIELD"  # the source itself reports the link (e.g. a proxy_wallet field)
    ONCHAIN_EVENT = "ONCHAIN_EVENT"  # a documented on-chain creation or authorization event
    HEURISTIC = "HEURISTIC"  # inferred (co-trading, shared funding); never a verified identity
    SYNTHETIC = "SYNTHETIC"  # fixture data


class RelationKind(str, Enum):
    PROXY_WALLET = "PROXY_WALLET"
    DEPOSIT_WALLET = "DEPOSIT_WALLET"
    SESSION_SIGNER = "SESSION_SIGNER"
    HEURISTIC_CLUSTER = "HEURISTIC_CLUSTER"


@dataclass(frozen=True)
class AccountRef:
    """A public pseudonymous account on one product (`product` names the venue/chain/network)."""

    product: str
    address: str

    def __post_init__(self) -> None:
        if not self.product or not _ADDRESS.fullmatch(self.product):
            raise ValueError(f"invalid product {self.product!r}")
        if not _ADDRESS.fullmatch(self.address):
            raise ValueError(f"invalid public address {self.address!r}")

    @property
    def key(self) -> str:
        return f"{self.product}|{self.address.lower()}"


@dataclass(frozen=True)
class ProxyMapping:
    mapping_id: str
    controller: AccountRef
    account: AccountRef
    relation: RelationKind
    valid_from: datetime
    valid_to: datetime | None  # None: open-ended as far as we know
    observed_at: datetime  # knowledge time
    basis: IdentityBasis
    evidence_ref: str

    def __post_init__(self) -> None:
        require_aware(self.valid_from, "valid_from")
        require_aware(self.observed_at, "observed_at")
        if self.valid_to is not None:
            require_aware(self.valid_to, "valid_to")
            if self.valid_to <= self.valid_from:
                raise ValueError("valid_to must be after valid_from")
        if not self.evidence_ref:
            raise ValueError("a mapping needs an evidence reference")


@dataclass(frozen=True)
class MappingRevocation:
    mapping_id: str
    ended_at: datetime  # world time the link stopped holding
    observed_at: datetime
    evidence_ref: str


class IdentityRegistry:
    """Append-only, bitemporal mapping store. Queries never see records observed after `known_at`."""

    def __init__(self) -> None:
        self._mappings: list[ProxyMapping] = []
        self._revocations: list[MappingRevocation] = []

    def add(self, mapping: ProxyMapping) -> None:
        if any(m.mapping_id == mapping.mapping_id for m in self._mappings):
            existing = next(m for m in self._mappings if m.mapping_id == mapping.mapping_id)
            if existing != mapping:
                raise ValueError(f"mapping {mapping.mapping_id} already recorded with different content")
            return
        self._mappings.append(mapping)

    def revoke(self, revocation: MappingRevocation) -> None:
        require_aware(revocation.ended_at, "ended_at")
        require_aware(revocation.observed_at, "observed_at")
        if not any(m.mapping_id == revocation.mapping_id for m in self._mappings):
            raise ValueError(f"unknown mapping {revocation.mapping_id}")
        self._revocations.append(revocation)

    @property
    def records(self) -> tuple[object, ...]:
        return tuple(self._mappings) + tuple(self._revocations)

    def _end(self, mapping: ProxyMapping, known_at: datetime) -> datetime | None:
        ends = [r.ended_at for r in self._revocations if r.mapping_id == mapping.mapping_id
                and r.observed_at <= known_at]
        candidates = [e for e in [mapping.valid_to, *ends] if e is not None]
        return min(candidates) if candidates else None

    def _active(self, at: datetime, known_at: datetime) -> list[ProxyMapping]:
        require_aware(at, "at")
        require_aware(known_at, "known_at")
        out = []
        for m in self._mappings:
            if m.observed_at > known_at or m.valid_from > at:
                continue
            end = self._end(m, known_at)
            if end is not None and at >= end:
                continue
            out.append(m)
        return out

    def accounts_for(self, controller: AccountRef, *, at: datetime, known_at: datetime) -> tuple[AccountRef, ...]:
        return tuple(sorted({m.account for m in self._active(at, known_at) if m.controller == controller},
                            key=lambda a: a.key))

    def controllers_for(self, account: AccountRef, *, at: datetime, known_at: datetime) -> tuple[AccountRef, ...]:
        """Every controller linked at `at`, as known at `known_at`. More than one is an ambiguity the
        caller must keep, never resolve by picking one."""
        return tuple(sorted({m.controller for m in self._active(at, known_at) if m.account == account},
                            key=lambda a: a.key))
