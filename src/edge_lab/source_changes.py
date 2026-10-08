"""Source change/event envelope v1 (#181 Deliverable E, ADR 0041 addendum). Pure, offline, fixture-fed.

This module is the reusable contract for "something a source said changed". A future crawler,
poller or stream recorder (each needing its own owner approval) would emit these envelopes. This
module never fetches, schedules, polls, subscribes or calls a model. Its only transport is
`read_envelopes`, which reads a local JSONL file, as `inplay_evidence.read_journal` does.

**What already existed and is reused here, not copied:**
- the source registry and its permission status: `sources.REGISTRY` / `SourceStatus`;
- payload digests: `provenance.payload_sha256` (canonical JSON);
- freshness: `freshness.Freshness`, `combine` and the fail-closed `require_fresh`;
- clocks with precision and uncertainty, provable ordering and latency with error bounds:
  `inplay_evidence.ClockReading`, `clock_order`, `measure_between`, `LatencyMeasurement`;
- evidence class: `inplay_evidence.DataKind`, `EvidenceStatus` and `check_evidence`;
- content freshness on the publication clock: `inplay_evidence.content_freshness` (through
  `ChangeEnvelope.as_observation`);
- conditioning context, dependence and the leadership vocabulary: `SourceContext`, `Dependence`,
  `LeadershipStatus`. Price-series lead-lag is `inplay_evidence.source_leadership`, unchanged;
- read coverage: `discovery.CoverageState`.

**What this module adds** (nothing above had it):
- `ChangeEnvelope`: one copy of one source's statement about one subject and aspect. It carries
  the subject identity and its basis, the content hash, our receipt and request clocks, the
  source's *claimed* publication time, revision, sequence and scope, coverage, evidence class and
  the actual fetch-cost basis (`FetchCost`; an unknown cost is None, never 0);
- `ChangeLedger`: append-only novelty, dedup and change detection with duplicate, echo,
  supersession, late-arrival, order-unknown, sequence-conflict and cross-source contradiction links;
- `attribution`: who we saw first. A site name, a stated attribution or apparent recency is
  never proof of original publication; `original_publication` is always UNKNOWN here;
- `response_latency`: per-event observation-to-market response, as a bounded window. It is
  UNKNOWN when identity, a baseline or a clock bound cannot be established;
- `first_report_leadership`: conditional, bidirectional first-report counts and lags between two
  sources over fixtures;
- `key_freshness` / `require_current`: an ambiguous or contradicted current value is UNKNOWN, so
  `require_fresh` fails closed on it.

Rules:
- Unknown stays unknown. A missing time, cost, identity or order is None or UNKNOWN, never 0,
  "now" or "receipt order".
- Receipt order alone never orders two copies of one source. Supersession needs a source sequence
  (same documented scope), provably ordered publication stamps, or non-overlapping fetch windows
  (the older copy's receipt provably before the newer copy's request).
- A contradiction is recorded and never resolved automatically. It may be lag, an error or a real
  disagreement; a human or a later, approved rule decides.
- Reports over envelopes (`response_latency`, `first_report_leadership`) accept SYNTHETIC and
  FIXTURE input only in this batch. RECORDED input needs an approved collector, an allocated
  experiment id and an evidence-use record first.
- Nothing here prices, sizes, submits or authorizes anything.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .discovery import CoverageState
from .freshness import Freshness, combine, parse_utc, require_fresh
from .inplay_evidence import (
    UNKNOWN_FAMILY, ClockOrigin, ClockReading, DataKind, Dependence, EvidenceStatus, LatencyMeasurement,
    LeadershipStatus, Ordering, Phase, SourceContext, SourceObservation, check_evidence, clock_order, content_freshness,
    measure_between,
)
from .provenance import canonical_json, payload_sha256, sha256_hex
from .sources import REGISTRY, SourceStatus

CONTRACT_VERSION = "source-change-v1"
JOURNAL_NAME = "source-change-v1"
REPORT_DATA_KINDS = frozenset({DataKind.SYNTHETIC, DataKind.FIXTURE})
NOT_PROOF_OF_ORIGIN = ("First observed by us is not first published. A site name, a stated attribution or a recent "
                       "stamp is a claim, never proof of the original publication time or source.")


# --------------------------------------------------------------------------- permission and identity


class SourcePermission(str, Enum):
    """The registry's status for a source id, plus UNREGISTERED for ids the registry does not know."""

    ACTIVE = "ACTIVE"
    PLANNED = "PLANNED"
    BLOCKED = "BLOCKED"
    UNREGISTERED = "UNREGISTERED"


_STATUS_PERMISSION = {SourceStatus.ACTIVE: SourcePermission.ACTIVE, SourceStatus.PLANNED: SourcePermission.PLANNED,
                      SourceStatus.BLOCKED: SourcePermission.BLOCKED}


def source_permission(source_id: str) -> SourcePermission:
    """The permission recorded in `sources.REGISTRY` (the one owner). Never self-asserted by an envelope."""
    spec = REGISTRY.get(source_id)
    return SourcePermission.UNREGISTERED if spec is None else _STATUS_PERMISSION[spec.status]


class IdentityBasis(str, Enum):
    SOURCE_NATIVE = "SOURCE_NATIVE"  # the source's own id in its own namespace (a Kalshi ticker from Kalshi)
    DECLARED_MAPPING = "DECLARED_MAPPING"  # mapped by a named, versioned rule (`mapping_ref`)
    UNKNOWN = "UNKNOWN"  # not established: the envelope is kept and counted, never merged


@dataclass(frozen=True)
class SubjectRef:
    """Which market, event or document an envelope is about."""

    namespace: str  # e.g. "kalshi:market", "nws:product:CLI:NYC"
    native_id: str | None
    basis: IdentityBasis
    mapping_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, str) or not self.namespace.strip():
            raise ValueError("namespace is required")
        if not isinstance(self.basis, IdentityBasis):
            raise ValueError("basis must be an IdentityBasis")
        if (self.basis is IdentityBasis.UNKNOWN) != (self.native_id is None):
            raise ValueError("an UNKNOWN identity has no native_id, and a known one needs it")
        if self.native_id is not None and (not isinstance(self.native_id, str) or not self.native_id.strip()):
            raise ValueError("native_id must be non-empty text or None")
        if (self.basis is IdentityBasis.DECLARED_MAPPING) != (self.mapping_ref is not None):
            raise ValueError("a DECLARED_MAPPING names its mapping_ref, and no other basis has one")

    @property
    def key(self) -> str | None:
        return None if self.native_id is None else f"{self.namespace}|{self.native_id}"

    def to_dict(self) -> dict[str, Any]:
        return {"namespace": self.namespace, "native_id": self.native_id, "basis": self.basis.value,
                "mapping_ref": self.mapping_ref}


# --------------------------------------------------------------------------- fetch cost


class CostBasis(str, Enum):
    """How a fetch cost is known. Ordered best first; aggregation takes the worst."""

    MEASURED = "MEASURED"  # from the provider's own accounting (quota headers, an invoice line, a ledger)
    DOCUMENTED = "DOCUMENTED"  # from the provider's documented price (`reference` names the page)
    ESTIMATED = "ESTIMATED"  # a stated estimate
    UNKNOWN = "UNKNOWN"  # not known: every amount is None, never 0


_COST_RANK = {CostBasis.MEASURED: 0, CostBasis.DOCUMENTED: 1, CostBasis.ESTIMATED: 2, CostBasis.UNKNOWN: 3}


def _non_negative_decimal(name: str, value: Any) -> None:
    if value is not None and (not isinstance(value, Decimal) or not value.is_finite() or value < 0):
        raise ValueError(f"{name} must be a non-negative Decimal or None, not {value!r}")


@dataclass(frozen=True)
class FetchCost:
    """The actual cost of the fetch that produced an envelope: requests, provider credits, money.

    None is unknown. Zero money is a claim that needs MEASURED or DOCUMENTED evidence and a
    `reference`; an UNKNOWN basis carries no amounts at all."""

    basis: CostBasis
    requests: int | None = None
    credits: Decimal | None = None
    money_usd: Decimal | None = None
    reference: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.basis, CostBasis):
            raise ValueError("basis must be a CostBasis")
        if self.requests is not None and (isinstance(self.requests, bool) or not isinstance(self.requests, int)
                                          or self.requests < 0):
            raise ValueError("requests must be a non-negative int or None")
        _non_negative_decimal("credits", self.credits)
        _non_negative_decimal("money_usd", self.money_usd)
        if self.basis is CostBasis.UNKNOWN:
            if any(v is not None for v in (self.requests, self.credits, self.money_usd)):
                raise ValueError("an UNKNOWN cost carries no amounts: unknown is None, never a number")
            return
        if self.requests is None:
            raise ValueError(f"a {self.basis.value} cost states how many requests it covers")
        if self.money_usd is not None and self.money_usd == 0 and (
                self.basis not in (CostBasis.MEASURED, CostBasis.DOCUMENTED) or not self.reference):
            raise ValueError("zero money needs MEASURED or DOCUMENTED evidence and a reference; free-first is not "
                             "free until shown")

    def to_dict(self) -> dict[str, Any]:
        return {"basis": self.basis.value, "requests": self.requests,
                "credits": None if self.credits is None else str(self.credits),
                "money_usd": None if self.money_usd is None else str(self.money_usd), "reference": self.reference}


UNKNOWN_COST = FetchCost(CostBasis.UNKNOWN)


def total_cost(costs: Iterable[FetchCost]) -> FetchCost:
    """Sum of fetch costs. One unknown amount makes that total unknown; the basis is the worst one; the
    references are kept; no inputs is UNKNOWN (never a zero total)."""
    items = list(costs)
    if not items:
        return UNKNOWN_COST
    worst = max(items, key=lambda c: _COST_RANK[c.basis]).basis
    if worst is CostBasis.UNKNOWN:
        return UNKNOWN_COST

    def _sum(values: list) -> Any:
        return None if any(v is None for v in values) else sum(values[1:], values[0])

    refs = "; ".join(sorted({c.reference for c in items if c.reference})) or None
    return FetchCost(worst, _sum([c.requests for c in items]), _sum([c.credits for c in items]),
                     _sum([c.money_usd for c in items]), refs)


# --------------------------------------------------------------------------- the envelope


def _reading_to_dict(r: ClockReading | None) -> dict[str, Any] | None:
    if r is None:
        return None
    return {"utc": r.utc, "origin": r.origin.value, "clock_id": r.clock_id,
            "precision_s": r.precision.total_seconds(),
            "uncertainty_s": None if r.uncertainty is None else r.uncertainty.total_seconds()}


def _reading_from_dict(d: Mapping[str, Any] | None) -> ClockReading | None:
    if d is None:
        return None
    unc = d.get("uncertainty_s")
    return ClockReading(d["utc"], ClockOrigin(d["origin"]), d["clock_id"], timedelta(seconds=d["precision_s"]),
                        None if unc is None else timedelta(seconds=unc))


def _context_to_dict(c: SourceContext) -> dict[str, Any]:
    return {"sport": c.sport, "market": c.market, "phase": c.phase.value, "regime": c.regime}


@dataclass(frozen=True)
class ChangeEnvelope:
    """One copy of one source's statement about one subject's aspect, with everything needed to use it honestly.

    `content` is the small normalized statement (the raw bytes stay in the evidence store, referenced by
    `raw_sha256` / `snapshot_ref`). `claimed_published` is the source's own stamp from the documented
    `publication_field`: a claim about this copy, never proof of original publication. `requested` is
    when our request left (None for a push message). Build one with `make_envelope`, which fills the
    permission from the registry and the content hash from the content."""

    source_id: str
    source_permission: SourcePermission
    kind: str  # the registry payload kind (the `SourceSpec.max_age` key)
    subject: SubjectRef
    aspect: str  # what about the subject: "rules_primary", "status", "close_time", "headline", ...
    content: Mapping[str, Any]
    content_sha256: str
    received: ClockReading
    data_kind: DataKind
    evidence: EvidenceStatus
    coverage: CoverageState
    cost: FetchCost
    requested: ClockReading | None = None
    claimed_published: ClockReading | None = None
    publication_field: str | None = None
    upstream_revision: str | None = None
    upstream_seq: int | None = None
    seq_scope: str | None = None  # what the sequence counts, as documented (e.g. "per subscription")
    raw_sha256: str | None = None
    snapshot_ref: str | None = None
    source_family: str = UNKNOWN_FAMILY
    upstream_ids: tuple[str, ...] = ()
    context: SourceContext = field(default_factory=lambda: SourceContext(None, None))
    attributed_to: str | None = None  # the source's own stated attribution ("via AP"): a claim, never verified

    def __post_init__(self) -> None:
        for name in ("source_id", "kind", "aspect"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
        if self.source_permission is not source_permission(self.source_id):
            raise ValueError(f"source_permission {self.source_permission!r} is not what sources.REGISTRY records "
                             f"for {self.source_id!r} ({source_permission(self.source_id).value}); permission is "
                             "never self-asserted")
        if not isinstance(self.subject, SubjectRef):
            raise ValueError("subject must be a SubjectRef")
        if not isinstance(self.content, Mapping):
            raise ValueError("content must be a mapping")
        if self.content_sha256 != payload_sha256(dict(self.content)):
            raise ValueError("content_sha256 does not match the content (provenance.payload_sha256)")
        if not isinstance(self.data_kind, DataKind):
            raise ValueError("data_kind must be a DataKind")
        if self.evidence is EvidenceStatus.UNAVAILABLE:
            raise ValueError("an envelope has content, so it cannot be UNAVAILABLE evidence")
        check_evidence(self.data_kind, self.evidence)
        if self.data_kind is DataKind.RECORDED and self.source_permission is not SourcePermission.ACTIVE:
            raise ValueError(f"RECORDED content from a {self.source_permission.value} source is refused: no collection "
                             "without a registered, ACTIVE source and its owner approval")
        if not isinstance(self.coverage, CoverageState) or self.coverage is CoverageState.FAILED:
            raise ValueError("coverage is COMPLETE or PARTIAL: a failed read is a source_health record, not a change")
        if not isinstance(self.cost, FetchCost):
            raise ValueError("cost must be a FetchCost (use UNKNOWN_COST when it is not known)")
        if not isinstance(self.received, ClockReading) or self.received.origin is not ClockOrigin.LOCAL:
            raise ValueError("received is a LOCAL clock reading")
        if self.requested is not None:
            if self.requested.origin is not ClockOrigin.LOCAL:
                raise ValueError("requested is a LOCAL clock reading")
            if clock_order(self.requested, self.received) is Ordering.AFTER:
                raise ValueError("a request cannot leave after its response arrived")
        if self.claimed_published is not None and self.claimed_published.origin is not ClockOrigin.SOURCE:
            raise ValueError("claimed_published is a SOURCE clock reading")
        if (self.claimed_published is None) != (self.publication_field is None):
            raise ValueError("a claimed publication time names the documented field it came from, and a field "
                             "without a time claims nothing")
        if self.claimed_published is not None and clock_order(self.claimed_published, self.received) is Ordering.AFTER:
            raise ValueError("FUTURE_PUBLICATION: the source stamp is provably after our receipt; the clocks are "
                             "inconsistent")
        if (self.upstream_seq is None) != (self.seq_scope is None):
            raise ValueError("a sequence number needs its documented scope, and a scope without a number orders nothing")
        if self.upstream_seq is not None and (isinstance(self.upstream_seq, bool) or not isinstance(self.upstream_seq, int)
                                              or self.upstream_seq < 0):
            raise ValueError("upstream_seq must be a non-negative int or None")
        if not isinstance(self.source_family, str) or not self.source_family:
            raise ValueError(f"source_family is required; use {UNKNOWN_FAMILY!r} when it is not known")
        if not isinstance(self.upstream_ids, tuple):
            raise ValueError("upstream_ids must be a tuple")
        if not isinstance(self.context, SourceContext):
            raise ValueError("context must be a SourceContext")

    @property
    def key(self) -> tuple[str, str] | None:
        """(subject key, aspect); None when identity is UNKNOWN."""
        return None if self.subject.key is None else (self.subject.key, self.aspect)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe and deterministic: enums by value, times as given, durations in seconds, Decimals as text."""
        return {
            "contract": CONTRACT_VERSION, "source_id": self.source_id, "source_permission": self.source_permission.value,
            "kind": self.kind, "subject": self.subject.to_dict(), "aspect": self.aspect, "content": dict(self.content),
            "content_sha256": self.content_sha256, "received": _reading_to_dict(self.received),
            "data_kind": self.data_kind.value, "evidence": self.evidence.value, "coverage": self.coverage.value,
            "cost": self.cost.to_dict(), "requested": _reading_to_dict(self.requested),
            "claimed_published": _reading_to_dict(self.claimed_published), "publication_field": self.publication_field,
            "upstream_revision": self.upstream_revision, "upstream_seq": self.upstream_seq,
            "seq_scope": self.seq_scope, "raw_sha256": self.raw_sha256, "snapshot_ref": self.snapshot_ref,
            "source_family": self.source_family, "upstream_ids": list(self.upstream_ids),
            "context": _context_to_dict(self.context), "attributed_to": self.attributed_to,
        }

    @property
    def envelope_id(self) -> str:
        """The digest of this exact copy. The same copy replayed has the same id."""
        return sha256_hex(canonical_json(self.to_dict()))

    def as_observation(self) -> SourceObservation:
        """The canonical `inplay_evidence.SourceObservation` for this copy (shared clocks and evidence rules)."""
        return SourceObservation(self.envelope_id, self.source_id, self.subject.key or IdentityBasis.UNKNOWN.value,
                                 self.received, self.context, self.evidence, self.data_kind,
                                 source_family=self.source_family, upstream_ids=self.upstream_ids,
                                 published=self.claimed_published)

    def max_age(self) -> timedelta | None:
        """The registry's objective for this payload kind; None (so UNKNOWN freshness) when it has none."""
        spec = REGISTRY.get(self.source_id)
        return None if spec is None else spec.max_age.get(self.kind)

    def freshness(self, now: datetime) -> Freshness:
        """Content freshness at `now`, on the publication clock (`inplay_evidence.content_freshness`)."""
        max_age = self.max_age()
        if max_age is None:
            if parse_utc(now) is None:
                raise ValueError("now must be timezone-aware")
            return Freshness.UNKNOWN
        return content_freshness(self.as_observation(), now=now, max_age=max_age)


def make_envelope(*, source_id: str, kind: str, subject: SubjectRef, aspect: str, content: Mapping[str, Any],
                  received: ClockReading, data_kind: DataKind, evidence: EvidenceStatus, coverage: CoverageState,
                  cost: FetchCost = UNKNOWN_COST, **optional: Any) -> ChangeEnvelope:
    """Build an envelope: the permission comes from the registry and the hash from the content."""
    return ChangeEnvelope(source_id=source_id, source_permission=source_permission(source_id), kind=kind,
                          subject=subject, aspect=aspect, content=dict(content),
                          content_sha256=payload_sha256(dict(content)), received=received, data_kind=data_kind,
                          evidence=evidence, coverage=coverage, cost=cost, **optional)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"not a decimal: {value!r}") from exc


def envelope_from_dict(d: Mapping[str, Any]) -> ChangeEnvelope:
    """The inverse of `ChangeEnvelope.to_dict`. Every check runs again; the stored hash must still match."""
    if d.get("contract") != CONTRACT_VERSION:
        raise ValueError(f"not a {CONTRACT_VERSION} envelope: {d.get('contract')!r}")
    s, c, ctx = d["subject"], d["cost"], d["context"]
    return ChangeEnvelope(
        source_id=d["source_id"], source_permission=SourcePermission(d["source_permission"]), kind=d["kind"],
        subject=SubjectRef(s["namespace"], s["native_id"], IdentityBasis(s["basis"]), s.get("mapping_ref")),
        aspect=d["aspect"], content=dict(d["content"]), content_sha256=d["content_sha256"],
        received=_reading_from_dict(d["received"]), data_kind=DataKind(d["data_kind"]),
        evidence=EvidenceStatus(d["evidence"]), coverage=CoverageState(d["coverage"]),
        cost=FetchCost(CostBasis(c["basis"]), c.get("requests"), _decimal(c.get("credits")),
                       _decimal(c.get("money_usd")), c.get("reference")),
        requested=_reading_from_dict(d.get("requested")), claimed_published=_reading_from_dict(d.get("claimed_published")),
        publication_field=d.get("publication_field"), upstream_revision=d.get("upstream_revision"),
        upstream_seq=d.get("upstream_seq"), seq_scope=d.get("seq_scope"), raw_sha256=d.get("raw_sha256"),
        snapshot_ref=d.get("snapshot_ref"), source_family=d.get("source_family", UNKNOWN_FAMILY),
        upstream_ids=tuple(d.get("upstream_ids", ())),
        context=SourceContext(ctx.get("sport"), ctx.get("market"), Phase(ctx.get("phase", "UNKNOWN")),
                              ctx.get("regime")),
        attributed_to=d.get("attributed_to"),
    )


def read_envelopes(path: Path) -> Iterator[ChangeEnvelope]:
    """Envelopes from a local JSONL file whose first line is `{"journal": "source-change-v1", "data_kind": ...}`.
    Every envelope must carry the header's data kind. Local file only: no network, ever."""
    with Path(path).open(encoding="utf-8") as fh:
        header = json.loads(fh.readline() or "null")
        if not isinstance(header, dict) or header.get("journal") != JOURNAL_NAME:
            raise ValueError(f"{path}: the first line must be a {JOURNAL_NAME} header")
        kind = DataKind(header["data_kind"])
        for number, line in enumerate(fh, start=2):
            if not line.strip():
                continue
            env = envelope_from_dict(json.loads(line))
            if env.data_kind is not kind:
                raise ValueError(f"{path}:{number}: {env.data_kind.value} envelope in a {kind.value} journal")
            yield env


# --------------------------------------------------------------------------- ordering two copies of one source


class OrderBasis(str, Enum):
    SOURCE_SEQUENCE = "SOURCE_SEQUENCE"  # the source's own sequence, same documented scope
    SOURCE_PUBLICATION = "SOURCE_PUBLICATION"  # the source's own stamps, provably ordered
    FETCH_WINDOWS = "FETCH_WINDOWS"  # one copy's receipt provably before the other's request


class CopyOrder(str, Enum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"
    UNORDERED = "UNORDERED"
    CONFLICT = "CONFLICT"  # the same sequence number with different content


def copy_order(a: ChangeEnvelope, b: ChangeEnvelope) -> tuple[CopyOrder, OrderBasis | None]:
    """Whether copy `a` of a source's statement is provably older (BEFORE) or newer (AFTER) than copy `b`.

    Receipt order alone is never used: two overlapping fetches can return in either order."""
    if a.source_id != b.source_id:
        raise ValueError("copy_order compares two copies from one source")
    if a.upstream_seq is not None and b.upstream_seq is not None and a.seq_scope == b.seq_scope:
        if a.upstream_seq == b.upstream_seq:
            same = a.content_sha256 == b.content_sha256
            return (CopyOrder.UNORDERED if same else CopyOrder.CONFLICT), OrderBasis.SOURCE_SEQUENCE
        return (CopyOrder.BEFORE if a.upstream_seq < b.upstream_seq else CopyOrder.AFTER), OrderBasis.SOURCE_SEQUENCE
    if a.claimed_published is not None and b.claimed_published is not None:
        o = clock_order(a.claimed_published, b.claimed_published)
        if o is not Ordering.UNORDERED:
            return CopyOrder(o.value), OrderBasis.SOURCE_PUBLICATION
    if b.requested is not None and clock_order(a.received, b.requested) is Ordering.BEFORE:
        return CopyOrder.BEFORE, OrderBasis.FETCH_WINDOWS
    if a.requested is not None and clock_order(b.received, a.requested) is Ordering.BEFORE:
        return CopyOrder.AFTER, OrderBasis.FETCH_WINDOWS
    return CopyOrder.UNORDERED, None


# --------------------------------------------------------------------------- the ledger


class ChangeKind(str, Enum):
    NEW = "NEW"  # this source's first statement on the key, content nobody has reported
    ECHO = "ECHO"  # this source's first statement on the key, content another source already reported
    REPLAYED = "REPLAYED"  # the identical copy again (same envelope_id): idempotent, counted
    DUPLICATE = "DUPLICATE"  # same source, content it currently holds: proof it stayed available, not news
    CHANGED = "CHANGED"  # same source, new content, provably newer than every current copy: supersedes them
    LATE_ARRIVAL = "LATE_ARRIVAL"  # same source, content provably older than a current copy: superseded on arrival
    ORDER_UNKNOWN = "ORDER_UNKNOWN"  # same source, new content, order not established: the key needs review
    SEQUENCE_CONFLICT = "SEQUENCE_CONFLICT"  # same sequence number, different content: the source contradicts itself
    UNKEYED = "UNKEYED"  # identity UNKNOWN: kept and counted, never merged


class LinkKind(str, Enum):
    DUPLICATE_OF = "DUPLICATE_OF"
    ECHO_OF = "ECHO_OF"
    SUPERSEDES = "SUPERSEDES"
    SUPERSEDED_BY = "SUPERSEDED_BY"
    UNORDERED_WITH = "UNORDERED_WITH"
    CONTRADICTS = "CONTRADICTS"  # differs from another source's current copy, or the same sequence's copy


@dataclass(frozen=True)
class ChangeRecord:
    arrival_index: int  # our observed sequence: the order envelopes reached the ledger
    envelope: ChangeEnvelope
    kind: ChangeKind
    order_basis: OrderBasis | None
    links: tuple[tuple[LinkKind, str], ...]
    novel: bool  # content never seen on this key before, from any source

    @property
    def envelope_id(self) -> str:
        return self.envelope.envelope_id


_TAKES_CURRENT = frozenset({ChangeKind.NEW, ChangeKind.ECHO, ChangeKind.CHANGED, ChangeKind.ORDER_UNKNOWN,
                            ChangeKind.SEQUENCE_CONFLICT})


class ChangeLedger:
    """Append-only novelty, dedup and change detection. `append` returns a new ledger; nothing is overwritten.

    Per (key, source) the ledger keeps the current copies: one when the order is established, several
    when it is not (ORDER_UNKNOWN or SEQUENCE_CONFLICT) until a provably newer copy resolves them."""

    def __init__(self) -> None:
        self._records: tuple[ChangeRecord, ...] = ()
        self._ids: dict[str, int] = {}
        self._current: dict[tuple[tuple[str, str], str], tuple[ChangeEnvelope, ...]] = {}
        self._seen: dict[tuple[str, str], dict[str, ChangeEnvelope]] = {}  # key -> content hash -> first holder

    @property
    def records(self) -> tuple[ChangeRecord, ...]:
        return self._records

    def _copy(self) -> "ChangeLedger":
        new = ChangeLedger()
        new._records, new._ids = self._records, dict(self._ids)
        new._current = dict(self._current)
        new._seen = {k: dict(v) for k, v in self._seen.items()}
        return new

    def append(self, env: ChangeEnvelope) -> "ChangeLedger":
        if not isinstance(env, ChangeEnvelope):
            raise ValueError("the ledger holds ChangeEnvelope only")
        out = self._copy()
        index = len(self._records)
        eid = env.envelope_id
        if eid in self._ids:
            rec = ChangeRecord(index, env, ChangeKind.REPLAYED, None,
                               ((LinkKind.DUPLICATE_OF, eid),), False)
            out._records += (rec,)
            return out
        out._ids[eid] = index
        key = env.key
        if key is None:
            out._records += (ChangeRecord(index, env, ChangeKind.UNKEYED, None, (), False),)
            return out
        seen = out._seen.setdefault(key, {})
        novel = env.content_sha256 not in seen
        cands = self._current.get((key, env.source_id), ())
        links: list[tuple[LinkKind, str]] = []
        basis: OrderBasis | None = None
        if not cands:
            if novel:
                kind = ChangeKind.NEW
            else:
                kind = ChangeKind.ECHO
                links.append((LinkKind.ECHO_OF, seen[env.content_sha256].envelope_id))
            current: tuple[ChangeEnvelope, ...] = (env,)
        else:
            kind, basis, current = self._classify(env, cands, links)
        if kind in _TAKES_CURRENT or current != cands:
            out._current[(key, env.source_id)] = current
        if kind in _TAKES_CURRENT:
            for (k, other_source), other in sorted(self._current.items(), key=lambda kv: kv[0][1]):
                if k != key or other_source == env.source_id:
                    continue
                for o in other:
                    if o.content_sha256 != env.content_sha256:
                        links.append((LinkKind.CONTRADICTS, o.envelope_id))
        if novel:
            seen[env.content_sha256] = env
        out._records += (ChangeRecord(index, env, kind, basis, tuple(links), novel),)
        return out

    @staticmethod
    def _classify(env: ChangeEnvelope, cands: tuple[ChangeEnvelope, ...], links: list
                  ) -> tuple[ChangeKind, OrderBasis | None, tuple[ChangeEnvelope, ...]]:
        same = [c for c in cands if c.content_sha256 == env.content_sha256]
        others = [c for c in cands if c.content_sha256 != env.content_sha256]
        orders = {c.envelope_id: copy_order(env, c) for c in others}
        bases = {b for _, b in orders.values() if b is not None}
        basis = min(bases, key=lambda b: list(OrderBasis).index(b)) if bases else None
        conflicts = [c for c in others if orders[c.envelope_id][0] is CopyOrder.CONFLICT]
        if conflicts:
            links.extend((LinkKind.CONTRADICTS, c.envelope_id) for c in conflicts)
            return ChangeKind.SEQUENCE_CONFLICT, OrderBasis.SOURCE_SEQUENCE, cands + (env,)
        if same:
            links.append((LinkKind.DUPLICATE_OF, same[0].envelope_id))
            if others and all(orders[c.envelope_id][0] is CopyOrder.AFTER for c in others):
                links.extend((LinkKind.SUPERSEDES, c.envelope_id) for c in others)
                return ChangeKind.DUPLICATE, basis, tuple(same)  # the held content is provably the newest
            return ChangeKind.DUPLICATE, basis, cands
        older_than = [c for c in others if orders[c.envelope_id][0] is CopyOrder.BEFORE]
        if older_than:
            links.extend((LinkKind.SUPERSEDED_BY, c.envelope_id) for c in older_than)
            return ChangeKind.LATE_ARRIVAL, basis, cands
        if all(orders[c.envelope_id][0] is CopyOrder.AFTER for c in others):
            links.extend((LinkKind.SUPERSEDES, c.envelope_id) for c in others)
            return ChangeKind.CHANGED, basis, (env,)
        links.extend((LinkKind.UNORDERED_WITH, c.envelope_id) for c in others
                     if orders[c.envelope_id][0] is CopyOrder.UNORDERED)
        return ChangeKind.ORDER_UNKNOWN, basis, cands + (env,)

    # ---- queries

    def keys(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted({k for k, _ in self._current}))

    def current(self, key: tuple[str, str]) -> dict[str, tuple[ChangeEnvelope, ...]]:
        """Per source, its current copies on `key` (more than one: the order is not established)."""
        return {s: c for (k, s), c in sorted(self._current.items(), key=lambda kv: kv[0][1]) if k == key}

    def contradictions(self, key: tuple[str, str]) -> tuple[tuple[str, str], ...]:
        """Source pairs whose current content on `key` differs (sorted). Recorded, never resolved."""
        cur = self.current(key)
        out = set()
        for a in cur:
            for b in cur:
                if a < b and {e.content_sha256 for e in cur[a]} != {e.content_sha256 for e in cur[b]}:
                    out.add((a, b))
        return tuple(sorted(out))

    def first_receipt(self, key: tuple[str, str], content_sha256: str, *, source_id: str | None = None
                      ) -> ClockReading | None:
        """The earliest receipt of this content on this key, or None when there is none or it is not provable
        (receipts on different clocks that overlap)."""
        cands = [r.envelope.received for r in self._records if r.envelope.key == key
                 and r.envelope.content_sha256 == content_sha256
                 and (source_id is None or r.envelope.source_id == source_id)]
        if not cands:
            return None
        cands.sort(key=lambda c: (c.at, c.clock_id))
        first = cands[0]
        for other in cands[1:]:
            if other.clock_id != first.clock_id and clock_order(first, other) is not Ordering.BEFORE:
                return None
        return first

    def source_yield(self, source_id: str) -> "SourceYield":
        recs = [r for r in self._records if r.envelope.source_id == source_id]
        counts = {k: sum(1 for r in recs if r.kind is k) for k in ChangeKind}
        novel = sum(1 for r in recs if r.novel)
        cost = total_cost(r.envelope.cost for r in recs)
        per_novel = None
        if cost.money_usd is not None and novel:
            per_novel = cost.money_usd / novel
        kinds = {r.envelope.data_kind for r in recs}
        return SourceYield(source_id, len(recs), tuple((k, counts[k]) for k in ChangeKind), novel, cost, per_novel,
                           tuple(sorted(k.value for k in kinds)))


@dataclass(frozen=True)
class SourceYield:
    """What one source's envelopes added: counts by kind, novel content, all-in fetch cost and money per novel
    item (None when the cost is unknown or nothing was novel; never a 0 that hides an unknown)."""

    source_id: str
    envelopes: int
    by_kind: tuple[tuple[ChangeKind, int], ...]
    novel: int
    cost: FetchCost
    money_per_novel: Decimal | None
    data_kinds: tuple[str, ...]


# --------------------------------------------------------------------------- attribution (who we saw first)


@dataclass(frozen=True)
class Attribution:
    key: tuple[str, str]
    content_sha256: str
    sources: tuple[str, ...]
    earliest_received_source: str | None  # None when no single source is provably first by our clock
    earliest_claimed_publication_source: str | None  # None when the claimed stamps do not order provably
    stated_attributions: tuple[tuple[str, str], ...]  # (source, what it says it is from): claims, unverified
    original_publication: str = "UNKNOWN"  # never established here
    note: str = NOT_PROOF_OF_ORIGIN


def _provably_first(readings: Sequence[tuple[str, ClockReading]]) -> str | None:
    """The one source whose reading is provably before every other's, else None."""
    for s, r in readings:
        if all(clock_order(r, q) is Ordering.BEFORE for t, q in readings if t != s):
            return s
    return None


def attribution(ledger: ChangeLedger, key: tuple[str, str], content_sha256: str) -> Attribution:
    """Which source we saw first with this content, and which claims the earliest publication. Neither is
    the original publisher: `original_publication` stays UNKNOWN."""
    recs = [r.envelope for r in ledger.records if r.envelope.key == key and r.envelope.content_sha256 == content_sha256]
    sources = tuple(sorted({e.source_id for e in recs}))
    received = []
    for s in sources:
        first = ledger.first_receipt(key, content_sha256, source_id=s)
        if first is None:
            received = []
            break
        received.append((s, first))
    published = []
    for s in sources:
        stamps = [e.claimed_published for e in recs if e.source_id == s and e.claimed_published is not None]
        if not stamps:
            published = []
            break
        published.append((s, min(stamps, key=lambda r: r.at)))
    stated = tuple(sorted({(e.source_id, e.attributed_to) for e in recs if e.attributed_to}))
    return Attribution(key, content_sha256, sources, _provably_first(received) if len(received) > 1 else
                       (received[0][0] if received else None),
                       _provably_first(published) if len(published) > 1 else (published[0][0] if published else None),
                       stated)


# --------------------------------------------------------------------------- freshness at the point of use


def key_freshness(ledger: ChangeLedger, key: tuple[str, str], now: datetime, *,
                  sources: Sequence[str] | None = None) -> tuple[Freshness, tuple[str, ...]]:
    """Worst-of freshness of the current copies on `key` (optionally from `sources` only). An ambiguous current
    copy, a contradiction between the sources used, or no copy at all is UNKNOWN."""
    cur = ledger.current(key)
    use = sorted(cur) if sources is None else list(sources)
    reasons: list[str] = []
    states: list[Freshness] = []
    for s in use:
        copies = cur.get(s, ())
        if not copies:
            reasons.append(f"NO_COPY: {s} has no current copy on this key")
            states.append(Freshness.UNKNOWN)
        elif len(copies) > 1:
            reasons.append(f"AMBIGUOUS: {s} has {len(copies)} current copies whose order is not established")
            states.append(Freshness.UNKNOWN)
        else:
            states.append(copies[0].freshness(now))
    used = {s: {e.content_sha256 for e in cur.get(s, ())} for s in use}
    for a in use:
        for b in use:
            if a < b and used[a] and used[b] and used[a] != used[b]:
                reasons.append(f"CONTRADICTION: {a} and {b} disagree")
                states.append(Freshness.UNKNOWN)
    return combine(*states), tuple(reasons)


def require_current(ledger: ChangeLedger, key: tuple[str, str], now: datetime, *,
                    sources: Sequence[str] | None = None) -> None:
    """Fail closed (`freshness.require_fresh`) unless every current copy used is FRESH, unambiguous and agreed."""
    state, reasons = key_freshness(ledger, key, now, sources=sources)
    require_fresh(state, what=f"{key[0]} {key[1]}" + (f" ({'; '.join(reasons)})" if reasons else ""))


# --------------------------------------------------------------------------- observation-to-market response


def _report_kind(envs: Iterable[ChangeEnvelope]) -> DataKind:
    kinds = {e.data_kind for e in envs}
    if not kinds:
        raise ValueError("no input")
    if len(kinds) > 1:
        raise ValueError(f"inputs of different data kinds are not combined: {sorted(k.value for k in kinds)}")
    kind = kinds.pop()
    if kind not in REPORT_DATA_KINDS:
        raise ValueError(f"{kind.value} input is refused in this batch: reports are fixture- and synthetic-fed; real "
                         "input needs an approved collector, an allocated experiment id and an evidence-use record")
    return kind


class TimeBasis(str, Enum):
    RECEIVED = "RECEIVED"  # our receipt clock
    PUBLISHED = "PUBLISHED"  # the source's claimed publication clock


def _at(env: ChangeEnvelope, basis: TimeBasis) -> ClockReading | None:
    return env.received if basis is TimeBasis.RECEIVED else env.claimed_published


class LinkBasis(str, Enum):
    SAME_ID = "SAME_ID"  # the observation is about the market itself
    DECLARED_MAPPING = "DECLARED_MAPPING"  # a named, versioned mapping links the event to the market
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SubjectLink:
    """Which market an observed event bears on, and how we know."""

    observed_key: str | None
    market_key: str | None
    basis: LinkBasis
    mapping_ref: str | None = None

    def __post_init__(self) -> None:
        if (self.basis is LinkBasis.DECLARED_MAPPING) != (self.mapping_ref is not None):
            raise ValueError("a DECLARED_MAPPING link names its mapping_ref, and no other basis has one")
        if self.basis is LinkBasis.SAME_ID and self.observed_key != self.market_key:
            raise ValueError("a SAME_ID link has one key on both sides")


class ResponseStatus(str, Enum):
    RESPONDED = "RESPONDED"  # the market changed within [lower, upper] after the observation
    NO_RESPONSE_OBSERVED = "NO_RESPONSE_OBSERVED"  # no change through the last capture (lower bound only)
    UNORDERED = "UNORDERED"  # a market change cannot be placed before or after the observation
    UNKNOWN = "UNKNOWN"  # identity, baseline or clocks cannot be established


@dataclass(frozen=True)
class ResponseLatency:
    """Observation-to-market response for one event, as a window. `lower`/`upper` are None when unknown."""

    observation_id: str
    market_key: str | None
    status: ResponseStatus
    lower: timedelta | None
    upper: timedelta | None
    start_basis: TimeBasis
    end_basis: TimeBasis
    capture_gap: timedelta | None  # the market captures that bracket the change; it bounds the resolution
    reasons: tuple[str, ...]
    data_kind: DataKind
    version: str = CONTRACT_VERSION
    note: str = ("A response window over sampled captures under the stated clocks; not causal, not a fill, and not "
                 "evidence of an edge.")


def response_latency(observation: ChangeEnvelope, market: Sequence[ChangeEnvelope], link: SubjectLink | None, *,
                     start_basis: TimeBasis = TimeBasis.RECEIVED,
                     end_basis: TimeBasis = TimeBasis.RECEIVED) -> ResponseLatency:
    """How long after `observation` the linked market's content changed, from market captures `market`.

    - Identity: `link` must tie the observation's subject to the market by SAME_ID or a DECLARED_MAPPING,
      and every market capture must be on the linked market. Otherwise UNKNOWN (never a silent filter).
    - Baseline: the latest capture provably before the observation. Without one, UNKNOWN.
    - The response lies between the last unchanged capture and the first changed capture that is provably
      after the observation; both ends are widened by the clocks' error bounds. An unknown cross-clock
      bound is UNKNOWN. A changed capture that is not provably before or after the observation is UNORDERED.
    - No change through the last capture is NO_RESPONSE_OBSERVED, with only a lower bound."""
    kind = _report_kind([observation, *market])
    common = dict(observation_id=observation.envelope_id, start_basis=start_basis, end_basis=end_basis,
                  data_kind=kind)
    mkey = None if link is None else link.market_key

    def unknown(*why: str) -> ResponseLatency:
        return ResponseLatency(market_key=mkey, status=ResponseStatus.UNKNOWN, lower=None, upper=None,
                               capture_gap=None, reasons=tuple(why), **common)

    if link is None or link.basis is LinkBasis.UNKNOWN or link.market_key is None:
        return unknown("IDENTITY_UNESTABLISHED: no SAME_ID or declared mapping links the observation to a market")
    if observation.subject.key is None or observation.subject.key != link.observed_key:
        return unknown(f"IDENTITY_MISMATCH: the observation is about {observation.subject.key!r}, the link about "
                       f"{link.observed_key!r}")
    wrong = sorted({e.subject.key or "UNKNOWN" for e in market if e.subject.key != link.market_key})
    if wrong:
        return unknown(f"IDENTITY_MISMATCH: market captures on {wrong} are not the linked market {link.market_key!r}")
    start = _at(observation, start_basis)
    if start is None:
        return unknown(f"START_UNKNOWN: the observation has no {start_basis.value} time")
    points = []
    for e in market:
        at = _at(e, end_basis)
        if at is None:
            return unknown(f"END_UNKNOWN: a market capture has no {end_basis.value} time")
        points.append((at, e))
    points.sort(key=lambda p: (p[0].at, p[1].envelope_id))
    before = [p for p in points if clock_order(p[0], start) is Ordering.BEFORE]
    if not before:
        if any(at.interval() is None or start.interval() is None for at, _ in points
               if at.clock_id != start.clock_id):
            return unknown("CLOCK_UNKNOWN: a cross-clock error bound is unknown, so no market capture is provably "
                           "before the observation")
        return unknown("NO_BASELINE: no market capture is provably before the observation")
    baseline = before[-1]
    last_same = baseline
    for at, e in points[points.index(baseline) + 1:]:
        changed = e.content_sha256 != baseline[1].content_sha256
        order = clock_order(at, start)
        if not changed:
            last_same = (at, e)
            continue
        if order is not Ordering.AFTER:
            return ResponseLatency(market_key=mkey, status=ResponseStatus.UNORDERED, lower=None, upper=None,
                                   capture_gap=None, reasons=(
                                       "UNORDERED: a changed market capture is not provably after the observation",),
                                   **common)
        low = measure_between(start, last_same[0], "last unchanged capture - observation")
        high = measure_between(start, at, "first changed capture - observation")
        if low is None or high is None or low.uncertainty is None or high.uncertainty is None:
            return unknown("CLOCK_UNKNOWN: a cross-clock error bound is unknown")
        lower = max(low.value - low.uncertainty, timedelta(0))
        return ResponseLatency(market_key=mkey, status=ResponseStatus.RESPONDED, lower=lower,
                               upper=high.value + high.uncertainty, capture_gap=at.at - last_same[0].at,
                               reasons=(), **common)
    low = measure_between(start, last_same[0], "last unchanged capture - observation")
    if low is None or low.uncertainty is None:
        return unknown("CLOCK_UNKNOWN: a cross-clock error bound is unknown")
    return ResponseLatency(market_key=mkey, status=ResponseStatus.NO_RESPONSE_OBSERVED,
                           lower=max(low.value - low.uncertainty, timedelta(0)), upper=None, capture_gap=None,
                           reasons=("NO_RESPONSE_OBSERVED: the market had not changed by the last capture",), **common)


# --------------------------------------------------------------------------- first-report leadership


@dataclass(frozen=True)
class FirstReportLeadership:
    """Which of two sources first reported the same content on the same key, counted in both directions."""

    version: str
    status: LeadershipStatus
    a_source: str
    b_source: str
    basis: TimeBasis
    condition: SourceContext | None
    dependence: Dependence
    matched: int
    a_first: int | None
    b_first: int | None
    unordered: int | None
    unmatched_a: int
    unmatched_b: int
    excluded_by_condition: int
    lags: tuple[tuple[str, str, LatencyMeasurement | None], ...]  # (key, aspect, b-first-window-end - a's)
    required_resolution: timedelta
    variants_tested: int
    reasons: tuple[str, ...]
    data_kind: DataKind
    not_a_causal_claim: str = ("Counts of which source's report window ended first, in both directions, under the "
                               "stated clock basis, capture resolution and dependence. Not proof of origin, not causal, "
                               "not a ranking, and not an input to any frozen baseline.")


def _report_window(ledger: ChangeLedger, source: str, key: tuple[str, str], content: str, basis: TimeBasis,
                   same_clock: bool) -> tuple[datetime | None, datetime] | None:
    """When `source` first reported `content` on `key`: (lower, upper). None when unknowable.

    PUBLISHED: the earliest claimed stamp's interval. RECEIVED: from the last earlier capture of this source on
    the key that did not hold the content (None: unbounded) to the first receipt that did."""
    envs = [r.envelope for r in ledger.records if r.envelope.key == key and r.envelope.source_id == source]
    holders = [e for e in envs if e.content_sha256 == content]
    if basis is TimeBasis.PUBLISHED:
        stamps = sorted((e.claimed_published for e in holders if e.claimed_published is not None), key=lambda r: r.at)
        if not stamps:
            return None
        iv = stamps[0].interval(same_clock=same_clock)
        return None if iv is None else iv
    first = min((e.received for e in holders), key=lambda r: r.at)
    hi = first.interval(same_clock=same_clock)
    if hi is None:
        return None
    prior = [e.received for e in envs if e.content_sha256 != content and clock_order(e.received, first) is Ordering.BEFORE]
    if not prior:
        return None, hi[1]
    lo = max(prior, key=lambda r: r.at).interval(same_clock=same_clock)
    return (None if lo is None else lo[0]), hi[1]


def first_report_leadership(ledger: ChangeLedger, a_source: str, b_source: str, *, basis: TimeBasis,
                            condition: SourceContext | None, required_resolution: timedelta, variants_tested: int,
                            min_ordered: int) -> FirstReportLeadership:
    """Over fixture envelopes in `ledger`, for each (key, content) both sources reported (under `condition`
    when given), whose report window ended first.

    A-first only when A's window ends strictly before B's begins, and the reverse; overlap is UNORDERED. A
    RECEIVED-basis window with no earlier capture is unbounded below, so its source can never be shown later
    than the other: polling cadence bounds every claim. INSUFFICIENT_RESOLUTION when a window is unknown
    (clock bound) or wider than `required_resolution`; INSUFFICIENT_EVIDENCE below `min_ordered`."""
    if isinstance(variants_tested, bool) or not isinstance(variants_tested, int) or variants_tested < 1:
        raise ValueError("variants_tested is the count of variants tried (>= 1); it is part of the result")
    if required_resolution <= timedelta(0) or min_ordered < 1:
        raise ValueError("thresholds must be positive")
    if a_source == b_source:
        raise ValueError("leadership compares two different sources")
    envs = [r.envelope for r in ledger.records if r.envelope.source_id in (a_source, b_source)
            and r.kind is not ChangeKind.REPLAYED]
    kind = _report_kind(envs)
    excluded = sum(1 for e in envs if condition is not None and e.context != condition)
    envs = [e for e in envs if condition is None or e.context == condition]
    reasons: list[str] = []
    fam = {s: {e.source_family for e in envs if e.source_id == s} for s in (a_source, b_source)}
    ups = {s: {u for e in envs if e.source_id == s for u in e.upstream_ids} for s in (a_source, b_source)}
    fa, fb = fam[a_source], fam[b_source]
    if (fa & fb) - {UNKNOWN_FAMILY} or ups[a_source] & ups[b_source]:
        dependence = Dependence.SHARED_SOURCE
        reasons.append("SHARED_SOURCE: same family or a shared upstream; one may be relaying the other")
    elif UNKNOWN_FAMILY in fa | fb or not fa or not fb:
        dependence = Dependence.UNKNOWN
        reasons.append("DEPENDENCE_UNKNOWN: a source family is UNKNOWN")
    else:
        dependence = Dependence.INDEPENDENT_AS_DECLARED
    items = {s: {(e.key, e.content_sha256) for e in envs if e.source_id == s and e.key is not None}
             for s in (a_source, b_source)}
    both = sorted(items[a_source] & items[b_source])
    clocks = {e.received.clock_id for e in envs} if basis is TimeBasis.RECEIVED else \
        {e.claimed_published.clock_id for e in envs if e.claimed_published is not None}
    same_clock = len(clocks) == 1
    common = dict(version=CONTRACT_VERSION, a_source=a_source, b_source=b_source, basis=basis, condition=condition,
                  dependence=dependence, matched=len(both), unmatched_a=len(items[a_source]) - len(both),
                  unmatched_b=len(items[b_source]) - len(both), excluded_by_condition=excluded,
                  required_resolution=required_resolution, variants_tested=variants_tested, data_kind=kind)
    if excluded:
        reasons.append(f"CONDITIONED: {excluded} envelope(s) outside the stated context were excluded")
    windows = []
    resolution = []
    for key, content in both:
        wa = _report_window(ledger, a_source, key, content, basis, same_clock)
        wb = _report_window(ledger, b_source, key, content, basis, same_clock)
        if wa is None or wb is None:
            resolution.append(f"{key}: a {basis.value} window has an UNKNOWN clock bound or no stamp")
            continue
        for name, w in (("a", wa), ("b", wb)):
            if w[0] is not None and w[1] - w[0] > required_resolution:
                resolution.append(f"{key}: {name} window {w[1] - w[0]} > required resolution")
        windows.append((key, wa, wb))
    if resolution:
        return FirstReportLeadership(status=LeadershipStatus.INSUFFICIENT_RESOLUTION, a_first=None, b_first=None,
                                     unordered=None, lags=(),
                                     reasons=tuple(reasons + [f"INSUFFICIENT_RESOLUTION: {r}" for r in resolution]),
                                     **common)
    a_first = b_first = unordered = 0
    lags = []
    for key, wa, wb in windows:
        if wb[0] is not None and wa[1] < wb[0]:
            a_first += 1
        elif wa[0] is not None and wb[1] < wa[0]:
            b_first += 1
        else:
            unordered += 1
        lag = LatencyMeasurement(wb[1] - wa[1], None if wa[0] is None or wb[0] is None else
                                 (wa[1] - wa[0]) + (wb[1] - wb[0]), "b window end - a window end")
        lags.append((key[0], key[1], lag))
    status = LeadershipStatus.REPORTED
    if a_first + b_first < min_ordered:
        status = LeadershipStatus.INSUFFICIENT_EVIDENCE
        reasons.append(f"INSUFFICIENT_EVIDENCE: {a_first + b_first} ordered first report(s) < {min_ordered}")
    return FirstReportLeadership(status=status, a_first=a_first, b_first=b_first, unordered=unordered,
                                 lags=tuple(lags), reasons=tuple(reasons), **common)
