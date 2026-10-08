"""The account-aware shadow (#160 package M, ADR 0047). Pure: no I/O, no clock, no state of its own.

The shadow is not a second decision chain. The orchestrator's SHADOW mode runs the one chain (`Orchestrator._decide`:
stream proof, control, the risk gate on a projection of the account, then the pre-egress steps) and stops where a
real decision would call `prepare_attempt`. This module holds what only the shadow needs:

- **A read-only process identity** (`ProcessIdentity.READ_ONLY`). An orchestrator started with it wraps the caller's
  `send` in a `ReadOnlySender`, which refuses every write request before the caller's callable is reached. It can
  arm OBSERVE_ONLY and SHADOW only (`READ_ONLY_MODES`), it holds no automation grant, it cancels nothing, and it runs
  on a shadow store of its own (worker ids start with `SHADOW_WORKER_PREFIX`; an executor refuses a shadow store and
  a read-only process refuses an executor's). It therefore never takes the live executor's egress lease and never
  marks the live executor's in-flight attempts unknown.
- **The hypothetical reservation.** A WOULD_SUBMIT carries the reservation `prepare_attempt` would have made, built
  by the reservation authority's own `new_reservation` and judged by its own capacity rule (`decide`), under fence
  token 0 and an id prefixed `shadow:`. It lives only in the cycle that made it: the cycle's later decisions see it
  as held (as a real reservation would be), and nothing writes it to the reservation tables, so it can never reduce
  real available cash or count against real capacity.
- **The verdict record** (`SHADOW_VERDICT`): the full intent, the outcome and every reason, the hypothetical
  reservation, the capacity rule's figures, the digest of the exact create request it would have sent, and the
  version of every input. The same inputs give the same verdict bytes.

The structural guarantee (ADR 0043, enforced by `tests/invariants/test_execution_boundary.py`): neither this module
nor the orchestrator imports `transport` or `signer`, directly or through any package module (a proxy), and the
read-only sender's inner callable is named only here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from . import control as ctl
from . import kalshi_wire as w
from .model import OrderIntent, canonical_json, sha256_text
from .reservations import ReservationAuthority, ReservationDecision, ReservationView

SHADOW_RECORD = "SHADOW_VERDICT"
VERDICT_SCHEMA = "edge-lab-shadow-verdict/1"
SHADOW_FENCE = 0  # never a real fence: the store's CHECK requires fence_token >= 1
SHADOW_PREFIX = "shadow:"
SHADOW_WORKER_PREFIX = "shadow-"
VERDICT_OUTCOMES = frozenset({"WOULD_SUBMIT", "BLOCKED"})


class ProcessIdentity(str, Enum):
    """What a process may do to the venue. Only EXECUTOR can ever send a write (and only in a sending mode)."""

    EXECUTOR = "EXECUTOR"
    READ_ONLY = "READ_ONLY"


READ_ONLY_MODES = frozenset({ctl.Mode.OBSERVE_ONLY, ctl.Mode.SHADOW})  # the modes a READ_ONLY process may arm


class ShadowWriteRefused(Exception):
    """A read-only process was asked to send something other than an allowlisted read. Nothing was sent."""


class ReadOnlySender:
    """The only network capability a READ_ONLY process holds: allowlisted GET requests pass to the caller's `send`;
    anything else (a write, a non-GET, something that is not a `WireRequest`) raises `ShadowWriteRefused` before
    the caller's callable is reached."""

    def __init__(self, send: Callable[[w.WireRequest], Any]):
        if not callable(send) or isinstance(send, ReadOnlySender):
            raise ValueError("ReadOnlySender wraps the caller's send callable once")
        self._inner_send = send

    def __call__(self, request: w.WireRequest) -> Any:
        # Exactly a WireRequest: a subclass could override `is_write`, `method` or `full_path` and lie. The decision
        # is then read from the endpoint's own spec (an Enum member, which no subclass can replace), never from a
        # method of the request.
        if type(request) is not w.WireRequest:
            raise ShadowWriteRefused(f"READ_ONLY_IDENTITY: only a kalshi_wire.WireRequest itself is sent, not "
                                     f"{type(request).__name__}")
        try:
            w.check_allowlisted(request)
        except ValueError as exc:
            raise ShadowWriteRefused(f"READ_ONLY_IDENTITY: not an allowlisted request ({exc})") from exc
        endpoint = request.endpoint
        spec = endpoint.value if isinstance(endpoint, w.Endpoint) else None
        if not isinstance(spec, w.EndpointSpec) or spec.bucket is not w.Bucket.READ \
                or spec.method is not w.HttpMethod.GET:
            raise ShadowWriteRefused(f"READ_ONLY_IDENTITY: {getattr(endpoint, 'name', endpoint)} is not a read")
        return self._inner_send(request)


def is_shadow_worker(worker_id: str) -> bool:
    return isinstance(worker_id, str) and worker_id.startswith(SHADOW_WORKER_PREFIX)


def hypothetical_reservation(intent: OrderIntent, *, attempt_no: int, at_utc: str) -> ReservationView:
    """The reservation `prepare_attempt` would create for `intent` (the authority's own `new_reservation`), with a
    `shadow:` id and fence token 0: it can never be mistaken for, or written as, a real one."""
    if isinstance(attempt_no, bool) or not isinstance(attempt_no, int) or attempt_no < 1:
        raise ValueError("attempt_no must be a positive int")
    return ReservationAuthority.new_reservation(
        intent, reservation_id=f"{SHADOW_PREFIX}{intent.client_order_id()}#{attempt_no}", fence_token=SHADOW_FENCE,
        at_utc=at_utc)


def _reservation_dict(r: ReservationView) -> dict[str, Any]:
    return {"reservation_id": r.reservation_id, "intent_key": r.intent_key, "scope_key": r.scope_key,
            "market_ticker": r.market_ticker, "side": r.side.value, "kind": r.kind.value,
            "client_order_id": r.client_order_id, "quantity": r.quantity, "limit_price": r.limit_price,
            "filled_quantity": r.filled_quantity, "cash_worst_case": r.cash_worst_case, "state": r.state.value,
            "fence_token": r.fence_token, "created_at_utc": r.created_at_utc}


def _capacity_dict(d: ReservationDecision) -> dict[str, Any]:
    return {"allowed": d.allowed, "reasons": list(d.reasons), "snapshot_revision": d.snapshot_revision,
            "cash_required": d.cash_required, "cash_available": d.cash_available,
            "inventory_available": d.inventory_available}


@dataclass(frozen=True)
class ShadowVerdict:
    """One shadow decision: what the chain concluded for one proposal, with everything it was concluded from.
    `reservation` is set exactly for WOULD_SUBMIT. `capacity` is None when the capacity rule was not asked (the
    proposal stopped earlier: arbitration, the deadline, the stream); None is never "no obligations"."""

    cycle: int
    decided_at_utc: str
    intent: OrderIntent
    outcome: str
    reasons: tuple[str, ...]
    reservation: ReservationView | None
    capacity: ReservationDecision | None
    request_digest: str | None
    inputs: tuple[tuple[str, str | None], ...]
    schema: str = VERDICT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != VERDICT_SCHEMA:
            raise ValueError(f"unknown verdict schema {self.schema!r}")
        if not isinstance(self.intent, OrderIntent):
            raise ValueError("intent must be an OrderIntent")
        if self.outcome not in VERDICT_OUTCOMES:
            raise ValueError(f"a shadow verdict is WOULD_SUBMIT or BLOCKED, not {self.outcome!r}")
        if (self.outcome == "WOULD_SUBMIT") == bool(self.reasons):
            raise ValueError("WOULD_SUBMIT has no reasons; BLOCKED states them")
        if (self.reservation is not None) != (self.outcome == "WOULD_SUBMIT"):
            raise ValueError("a hypothetical reservation exists exactly for WOULD_SUBMIT")
        if self.reservation is not None and (not self.reservation.reservation_id.startswith(SHADOW_PREFIX)
                                             or self.reservation.fence_token != SHADOW_FENCE):
            raise ValueError("a hypothetical reservation carries a shadow id and fence token 0")
        if self.outcome == "WOULD_SUBMIT" and (self.capacity is None or not self.capacity.allowed
                                               or self.request_digest is None):
            raise ValueError("WOULD_SUBMIT needs an allowed capacity decision and the request it would send")
        if not isinstance(self.inputs, tuple) or not all(
                isinstance(p, tuple) and len(p) == 2 and isinstance(p[0], str) for p in self.inputs):
            raise ValueError("inputs must be a tuple of (name, version) pairs")
        object.__setattr__(self, "inputs", tuple(sorted(self.inputs)))

    def to_record(self) -> dict[str, Any]:
        return {"schema": self.schema, "cycle": self.cycle, "decided_at_utc": self.decided_at_utc,
                "intent": self.intent.to_dict(), "intent_digest": self.intent.digest(), "outcome": self.outcome,
                "reasons": list(self.reasons),
                "hypothetical_reservation": None if self.reservation is None else _reservation_dict(self.reservation),
                "capacity": None if self.capacity is None else _capacity_dict(self.capacity),
                "request_digest": self.request_digest, "inputs": [list(p) for p in self.inputs]}

    def digest(self) -> str:
        return sha256_text(canonical_json(self.to_record()))
