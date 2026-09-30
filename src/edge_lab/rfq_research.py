"""RFQ research: a pure, fixture-fed model of Kalshi's event-contract RFQ lifecycle (R4, ADR 0042).

This is an observation and accounting contract, not a participant. Nothing here connects,
authenticates, subscribes, creates an RFQ, quotes, accepts or confirms. Inputs are recorded or
synthetic messages handed in by a caller; outputs are research facts. RFQ participation is not
authorized (`docs/EXECUTION_PLAN.md`, 2026-09-30 directive), and `venues.KALSHI` keeps
`execution_authorized` False. `hypothetical_check` therefore always ends with
PARTICIPATION_NOT_AUTHORIZED, the way `execution_ticket.pre_submit_checks` always ends with
EXECUTION_NOT_AUTHORIZED.

Semantics come from the public Kalshi documentation read on 2026-09-30 (`RFQ_DOC_SOURCES`;
the matrix and every conflict are in `docs/research/RFQ_FEASIBILITY_2026-09.md`). Anything the
documentation does not define is UNSUPPORTED or UNKNOWN here, never a convenient default:

- **Visibility.** `rfq_created` / `rfq_deleted` reach every authenticated subscriber; quote
  events reach only the quote's creator and the RFQ's creator. A price we could not have seen
  is UNAVAILABLE (None), never 0 and never inferred.
- **Quantities are layered.** Requested size is a demand upper bound. An accept notification,
  a maker confirmation and a `quote_executed` ("orders are placed") are not fills. Only fill
  records give filled quantity.
- **Binding point.** Documented: once the maker confirms, neither party can withdraw.
- **Order independence.** State is derived from the *set* of distinct events, so duplicates and
  out-of-order delivery give the same answer. Contradictory evidence is UNKNOWN.
- **Conservative exposure.** An own quote or RFQ keeps its worst-case principal reserved until
  the quote's own CANCELLED status is observed. A closed RFQ, a replacement, a lapsed window or a
  missing event releases nothing, and any own fill that cannot be attributed blocks every release.
  Simultaneous obligations are reserved through the canonical owner,
  `execution_ticket.reserve_simultaneous_obligations`, per exchange index; shared combo legs never
  share collateral.
- **Currency needs evidence.** "This quote is current" needs a caller-stated observation time
  within `max_age` and gap-free channel sequence numbers; otherwise OBSERVATION_STALE_OR_GAPPED.
- **Input bound.** The communications channel ignores market filtering, so the bound applies to
  every received message, before any local filter, and is checked without reading past it. Over
  the bound the whole batch is refused, never truncated. The local filter applies only to the
  public RFQ events; our own party events and fills are always kept.
- **Fees.** No RFQ or combo fee is verified. A fee-inclusive size needs a caller-supplied fee
  function; without one it is FEE_UNSUPPORTED.

Pure, deterministic, stdlib-only and network-free. Perpetual-futures (margin) behaviour is out of
scope and is not modelled.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from enum import Enum
from itertools import islice
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from .freshness import parse_utc
from .provenance import payload_sha256
from .execution_ticket import HELD_OBLIGATION_STATES, ObligationState
from .execution_ticket import Obligation as CanonicalObligation
from .execution_ticket import ObligationReservation as CanonicalReservation
from .execution_ticket import reserve_simultaneous_obligations
from .venues import KALSHI

RFQ_DOCS_FETCHED_UTC = "2026-09-30T02:26:52Z"
RFQ_DOC_SOURCES = (
    "https://docs.kalshi.com/getting_started/rfqs",
    "https://docs.kalshi.com/websockets/communications",
    "https://docs.kalshi.com/fix/rfq-messages",
    "https://docs.kalshi.com/api-reference/communications/get-quotes",
    "https://docs.kalshi.com/getting_started/maintenance_and_pauses",
)

CONTRACT_STEP = Decimal("0.01")  # documented fixed-point contract granularity
ONE = Decimal(1)
ZERO = Decimal(0)


class Visibility(str, Enum):
    VISIBLE = "VISIBLE"
    UNAVAILABLE = "UNAVAILABLE"  # exists, but private to other participants: unknown, never zero
    UNSUPPORTED = "UNSUPPORTED"  # the documentation does not define it


class TimingClass(str, Enum):
    STANDARD = "STANDARD"
    HVM = "HVM"  # High Volatility Market; every combo market is one


# The RFQ guide's table. The FIX page states a flat 30 s confirmation window: a recorded conflict.
CONFIRMATION_WINDOW = MappingProxyType({TimingClass.STANDARD: timedelta(seconds=30),
                                        TimingClass.HVM: timedelta(seconds=3)})
EXECUTION_TIMER = MappingProxyType({TimingClass.STANDARD: timedelta(seconds=15),
                                    TimingClass.HVM: timedelta(seconds=1)})


class Kind(str, Enum):
    RFQ_CREATED = "rfq_created"  # communications channel, every subscriber
    RFQ_DELETED = "rfq_deleted"  # communications channel, every subscriber
    QUOTE_CREATED = "quote_created"  # communications channel, parties only
    QUOTE_ACCEPTED = "quote_accepted"  # communications channel, parties only; carries no acceptance time
    QUOTE_EXECUTED = "quote_executed"  # communications channel, parties only: orders placed, not fills
    # Not channel events. Fixture adapters for REST quote status (`confirmed`, `cancelled`) and for
    # the member's own fill records (`GET /portfolio/fills`, the `fill` channel).
    QUOTE_CONFIRMED = "quote_confirmed"
    QUOTE_CANCELLED = "quote_cancelled"
    FILL = "fill"


PUBLIC_KINDS = frozenset({Kind.RFQ_CREATED, Kind.RFQ_DELETED})
PARTY_ONLY = frozenset(Kind) - PUBLIC_KINDS


class QuoteState(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"  # requester accepted; the maker has not confirmed: not binding on the maker
    CONFIRMED = "CONFIRMED"  # binding: neither party can withdraw (documented)
    ORDERS_PLACED = "ORDERS_PLACED"  # `quote_executed` or a fill: orders entered
    CANCELLED = "CANCELLED"  # the quote's own terminal status: the only releasing state
    REPLACED = "REPLACED"  # a later quote by the same maker exists; still reserved until CANCELLED is seen
    RFQ_CLOSED_REASON_UNKNOWN = "RFQ_CLOSED_REASON_UNKNOWN"  # rfq_deleted seen; this quote's fate unknown
    UNKNOWN = "UNKNOWN"  # contradictory or undocumented evidence


RELEASED_STATES = frozenset({QuoteState.CANCELLED})
REQUESTER_BOUND_STATES = frozenset({QuoteState.ACCEPTED, QuoteState.CONFIRMED, QuoteState.ORDERS_PLACED,
                                    QuoteState.UNKNOWN})


class SizeMode(str, Enum):
    CONTRACTS = "CONTRACTS"  # never reduced for fees under either target-cost mode
    TARGET_COST_FEE_INCLUSIVE = "TARGET_COST_FEE_INCLUSIVE"  # default: the target caps principal + taker fee
    TARGET_COST_PRINCIPAL_ONLY = "TARGET_COST_PRINCIPAL_ONLY"  # target_cost_excludes_fees: fee on top


class RfqResearchError(ValueError):
    pass


def _dec(value: Any) -> Decimal | None:
    """A finite Decimal from a fixed-point string or number. Missing or malformed is None, never 0."""
    if value is None or isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _nonneg(value: Any) -> Decimal | None:
    d = _dec(value)
    return d if d is not None and d >= 0 else None


# --------------------------------------------------------------------------- events


@dataclass(frozen=True)
class Leg:
    event_ticker: str
    market_ticker: str
    side: str  # "yes" | "no"


@dataclass(frozen=True)
class RfqEvent:
    """One received message, normalised. `key` is content-derived: the transport fields (sid, seq,
    sending_ts_ms) and our own receipt stamp (`received_at_utc`) are excluded, so a redelivered
    message is the same event. Two genuinely separate but identical messages also collapse (C1)."""

    kind: Kind | None  # None: an undocumented message type (kept and counted, never used)
    raw_type: str
    key: str
    rfq_id: str | None
    quote_id: str | None
    rfq_creator_id: str | None
    quote_creator_id: str | None
    market_ticker: str | None
    at_utc: datetime | None  # a documented venue timestamp in the message, if any
    received_at_utc: datetime | None = None  # the caller's receipt time: local, not a venue time
    sid: int | None = None
    seq: int | None = None
    contracts: Decimal | None = None  # RFQ contracts_fp; a fill's count_fp
    target_cost: Decimal | None = None
    target_cost_excludes_fees: bool | None = None
    legs: tuple[Leg, ...] = ()
    yes_bid: Decimal | None = None
    no_bid: Decimal | None = None
    yes_contracts_offered: Decimal | None = None
    no_contracts_offered: Decimal | None = None
    accepted_side: str | None = None
    contracts_accepted: Decimal | None = None
    order_id: str | None = None
    fill_id: str | None = None
    malformed: bool = False


_NOT_CONTENT = ("sid", "seq", "sending_ts_ms", "received_at_utc")
# Documented venue timestamps. `quote_accepted` has none (its acceptance time is taken from the
# caller's receipt stamp); REST quote status carries confirmed_ts / cancelled_ts; fills created_time.
_TIME_FIELDS = ("created_ts", "deleted_ts", "confirmed_ts", "executed_ts", "cancelled_ts", "created_time")
_SIZE_FIELDS = ("contracts_fp", "count_fp", "target_cost_dollars", "rfq_target_cost_dollars",
                "yes_contracts_offered_fp", "no_contracts_offered_fp", "contracts_accepted_fp")


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_message(raw: Mapping[str, Any]) -> RfqEvent:
    """Normalise one documented message (`{"type": ..., "msg": {...}}`). Never raises on content:
    an undocumented type has `kind` None; a message missing its identifiers, with a bid outside
    [0, 1] or with a negative size is `malformed`. An unparseable value is None (unknown)."""
    raw_type = str(raw.get("type", ""))
    msg = raw.get("msg") if isinstance(raw.get("msg"), Mapping) else {}
    try:
        kind: Kind | None = Kind(raw_type)
    except ValueError:
        kind = None
    key = payload_sha256({"type": raw_type, "msg": msg,
                          **{k: v for k, v in raw.items() if k not in _NOT_CONTENT + ("type", "msg")}})
    at = next((parse_utc(msg.get(f)) for f in _TIME_FIELDS if msg.get(f) is not None), None)
    is_rfq_kind = kind in PUBLIC_KINDS
    rfq_id = msg.get("id") if is_rfq_kind else msg.get("rfq_id")
    malformed = False
    legs: list[Leg] = []
    for leg in msg.get("mve_selected_legs") or ():
        if not isinstance(leg, Mapping) or leg.get("side") not in ("yes", "no") \
                or not leg.get("market_ticker") or not leg.get("event_ticker"):
            malformed = True
            continue
        legs.append(Leg(str(leg["event_ticker"]), str(leg["market_ticker"]), str(leg["side"])))
    for name in ("yes_bid_dollars", "no_bid_dollars"):
        bid = _dec(msg.get(name))
        if bid is not None and not ZERO <= bid <= ONE:
            malformed = True
    for name in _SIZE_FIELDS:
        size = _dec(msg.get(name))
        if size is not None and size < 0:
            malformed = True
    excl = msg.get("target_cost_excludes_fees")
    event = RfqEvent(
        kind=kind, raw_type=raw_type, key=key,
        rfq_id=None if rfq_id is None else str(rfq_id),
        quote_id=_s(msg.get("quote_id")),
        rfq_creator_id=_s(msg.get("creator_id") if is_rfq_kind else msg.get("rfq_creator_id")),
        quote_creator_id=_s(msg.get("quote_creator_id")),
        market_ticker=_s(msg.get("market_ticker")), at_utc=at,
        received_at_utc=parse_utc(raw.get("received_at_utc")),
        sid=_int(raw.get("sid")), seq=_int(raw.get("seq")),
        contracts=_nonneg(msg.get("contracts_fp") if kind is not Kind.FILL else msg.get("count_fp")),
        target_cost=_nonneg(msg.get("target_cost_dollars", msg.get("rfq_target_cost_dollars"))),
        target_cost_excludes_fees=excl if isinstance(excl, bool) else None,
        legs=tuple(legs),
        yes_bid=_nonneg(msg.get("yes_bid_dollars")), no_bid=_nonneg(msg.get("no_bid_dollars")),
        yes_contracts_offered=_nonneg(msg.get("yes_contracts_offered_fp")),
        no_contracts_offered=_nonneg(msg.get("no_contracts_offered_fp")),
        accepted_side=msg.get("accepted_side") if msg.get("accepted_side") in ("yes", "no") else None,
        contracts_accepted=_nonneg(msg.get("contracts_accepted_fp")),
        order_id=_s(msg.get("order_id")), fill_id=_s(msg.get("fill_id")),
        malformed=malformed,
    )
    needs_quote = kind in PARTY_ONLY and kind is not Kind.FILL
    if kind is not None and ((kind is not Kind.FILL and not event.rfq_id) or (needs_quote and not event.quote_id)
                             or (kind is Kind.FILL and not (event.fill_id and event.order_id))):
        return replace(event, malformed=True)
    return event


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


# --------------------------------------------------------------------------- observer and views


@dataclass(frozen=True)
class Observer:
    """Who is looking. `comm_id` is the member's public communications id; None means no
    authenticated session, which sees nothing on the communications channel (it needs auth)."""

    comm_id: str | None

    @property
    def authenticated(self) -> bool:
        return bool(self.comm_id)


@dataclass(frozen=True)
class QuoteView:
    quote_id: str
    rfq_id: str
    own: bool  # we created the quote
    on_own_rfq: bool  # we created the RFQ
    state: QuoteState
    reasons: tuple[str, ...]
    yes_bid: Decimal | None
    no_bid: Decimal | None
    yes_contracts: Decimal | None
    no_contracts: Decimal | None
    created_at_utc: datetime | None
    accepted_side: str | None  # only when exactly one acceptance was seen
    accepted_received_at_utc: datetime | None  # our receipt of the acceptance, not a venue time
    contracts_accepted_notified: Decimal | None
    order_ids: tuple[str, ...]
    filled_contracts: Decimal | None  # None: no usable fill record observed (not zero)


@dataclass(frozen=True)
class RfqView:
    rfq_id: str
    own: bool
    open: bool | None  # None: no rfq_created/rfq_deleted seen for it
    market_ticker: str | None
    requested_contracts: Decimal | None  # a demand upper bound, not achievable volume
    target_cost: Decimal | None
    size_mode: SizeMode | None
    legs: tuple[Leg, ...]
    timing_class: TimingClass | None  # combos are HVM; otherwise UNKNOWN unless supplied
    competitor_quote_prices: Visibility


@dataclass(frozen=True)
class ObservationReport:
    status: str  # OK | REFUSED_INPUT_BOUND | REFUSED_NOT_AUTHENTICATED
    received_messages: str  # every message received before any local filter; ">N" when refused over the bound
    kept_messages: int
    duplicate_messages: int
    undocumented_messages: tuple[str, ...]
    malformed_messages: int
    not_addressed_to_observer: int  # party-only events for another pair: contradicts the docs, ignored
    rfqs: Mapping[str, RfqView] = field(default_factory=dict)
    quotes: Mapping[str, QuoteView] = field(default_factory=dict)
    requested_contracts_upper_bound: Decimal | None = None  # contracts-sized RFQs only
    requested_target_cost_dollars: Decimal | None = None  # target-cost RFQs: not convertible without a price
    accepted_contracts_notified: Decimal | None = None  # own quotes and RFQs only; not a fill
    filled_contracts: Decimal | None = None  # own fills only; None when none are usable
    unattributed_fills: int = 0  # own fill ids matching no observed quote_executed order id
    conflicting_fills: tuple[str, ...] = ()  # fill ids seen with differing payloads: UNKNOWN
    seq_gaps: int | None = None  # missing channel sequence numbers; None: no sequence evidence
    other_parties_fills: Visibility = Visibility.UNAVAILABLE
    competitor_quote_prices: Visibility = Visibility.UNAVAILABLE
    queue_rank: Visibility = Visibility.UNSUPPORTED  # RFQ quotes have no documented queue or rank


def _refused(status: str, received: str) -> ObservationReport:
    return ObservationReport(status=status, received_messages=received, kept_messages=0, duplicate_messages=0,
                             undocumented_messages=(), malformed_messages=0, not_addressed_to_observer=0)


def _seq_gaps(events: Iterable[RfqEvent]) -> int | None:
    by_sid: dict[int | None, set[int]] = {}
    for e in events:
        if e.seq is not None:
            by_sid.setdefault(e.sid, set()).add(e.seq)
    if not by_sid:
        return None
    return sum(max(seqs) - min(seqs) + 1 - len(seqs) for seqs in by_sid.values())


def _unique(values: Iterable[Any]) -> Any:
    found = {v for v in values if v is not None}
    return next(iter(found)) if len(found) == 1 else None


def observe(messages: Iterable[Mapping[str, Any]], observer: Observer, *, max_messages: int,
            keep: Callable[[RfqEvent], bool] | None = None,
            timing_class: Mapping[str, TimingClass] | None = None) -> ObservationReport:
    """Fold received messages into per-RFQ and per-quote views for `observer`.

    `max_messages` bounds everything received (the channel ignores market filtering). At most
    `max_messages + 1` items are read from `messages`; over the bound the batch is refused whole.
    `keep` filters only public RFQ events; party events and fills are always kept. `timing_class`
    maps a market ticker to its documented class; a combo (MVE legs present) is always HVM."""
    if not isinstance(max_messages, int) or isinstance(max_messages, bool) or max_messages < 0:
        raise RfqResearchError("max_messages must be a non-negative whole number")
    received = list(islice(iter(messages), max_messages + 1))
    if len(received) > max_messages:
        return _refused("REFUSED_INPUT_BOUND", f">{max_messages}")
    if not observer.authenticated:
        return _refused("REFUSED_NOT_AUTHENTICATED", str(len(received)))

    parsed: list[RfqEvent] = []
    seen: dict[str, RfqEvent] = {}
    receipt: dict[str, datetime] = {}
    duplicates = malformed = foreign = 0
    undocumented: list[str] = []
    for raw in received:
        event = parse_message(raw) if isinstance(raw, Mapping) else None
        if event is None or event.malformed:
            malformed += 1
            continue
        if event.kind is None:
            undocumented.append(event.raw_type)
            continue
        parsed.append(event)
        if event.received_at_utc is not None:
            prev = receipt.get(event.key)
            receipt[event.key] = event.received_at_utc if prev is None else min(prev, event.received_at_utc)
        if event.key in seen:
            duplicates += 1
            continue
        seen[event.key] = event
    # Sorted by content key: every later choice is independent of arrival order.
    events = sorted((replace(e, received_at_utc=receipt.get(e.key)) for e in seen.values()
                     if e.kind not in PUBLIC_KINDS or keep is None or keep(e)), key=lambda e: e.key)

    me = observer.comm_id
    rfq_events: dict[str, list[RfqEvent]] = {}
    quote_events: dict[str, list[RfqEvent]] = {}
    fills_by_id: dict[str, list[RfqEvent]] = {}
    for e in events:
        if e.kind is Kind.FILL:
            fills_by_id.setdefault(e.fill_id, []).append(e)  # own fill records; one fill id, one fill
        elif e.kind in PUBLIC_KINDS:
            rfq_events.setdefault(e.rfq_id, []).append(e)
        else:
            quote_events.setdefault(e.quote_id, []).append(e)
    conflicting = tuple(sorted(fid for fid, fs in fills_by_id.items() if len(fs) > 1))
    fills_by_order: dict[str, list[RfqEvent]] = {}
    for fid, fs in fills_by_id.items():
        fills_by_order.setdefault(fs[0].order_id, []).append(fs[0])  # conflicting ones are flagged below

    rfq_creator: dict[str, str | None] = {}
    for rid in {e.rfq_id for e in events if e.rfq_id}:
        rfq_creator[rid] = _unique(e.rfq_creator_id for e in events
                                   if e.rfq_id == rid and e.rfq_creator_id not in (None, "0"))

    drafts: dict[str, dict[str, Any]] = {}
    for qid, evs in quote_events.items():
        rfq_id = _unique(e.rfq_id for e in evs)
        maker = _unique(e.quote_creator_id for e in evs)
        own = maker == me
        on_own_rfq = rfq_creator.get(rfq_id) == me
        if not (own or on_own_rfq):
            foreign += len(evs)  # documented as never delivered to a non-party: do not use it
            continue
        drafts[qid] = {"evs": evs, "rfq_id": rfq_id, "maker": maker, "own": own, "on_own_rfq": on_own_rfq}

    rfqs: dict[str, RfqView] = {}
    for rid, evs in rfq_events.items():
        created = next((e for e in evs if e.kind is Kind.RFQ_CREATED), None)
        deleted = any(e.kind is Kind.RFQ_DELETED for e in evs)
        src = created or evs[0]
        legs = src.legs
        tclass = TimingClass.HVM if legs else (timing_class or {}).get(src.market_ticker or "")
        # The channel's rfq_created carries no target_cost_excludes_fees: the fee mode of a
        # target-cost RFQ seen there is unknown (None), not assumed to be the default.
        if src.target_cost is not None:
            mode = {True: SizeMode.TARGET_COST_PRINCIPAL_ONLY, False: SizeMode.TARGET_COST_FEE_INCLUSIVE,
                    None: None}[src.target_cost_excludes_fees]
        else:
            mode = SizeMode.CONTRACTS if src.contracts is not None else None
        own = rfq_creator.get(rid) == me
        rfqs[rid] = RfqView(rfq_id=rid, own=own, open=not deleted, market_ticker=src.market_ticker,
                            requested_contracts=src.contracts if mode is SizeMode.CONTRACTS else None,
                            target_cost=src.target_cost, size_mode=mode, legs=legs, timing_class=tclass,
                            competitor_quote_prices=Visibility.VISIBLE if own else Visibility.UNAVAILABLE)

    # Replacement: a maker's later quote on the same RFQ replaces its earlier one (documented).
    peers_of: dict[tuple[str | None, str | None], list[tuple[datetime | None, str]]] = {}
    for qid, d in drafts.items():
        created_at = next((e.at_utc for e in d["evs"] if e.kind is Kind.QUOTE_CREATED), None)
        peers_of.setdefault((d["rfq_id"], d["maker"]), []).append((created_at, qid))

    quotes: dict[str, QuoteView] = {}
    for qid, d in drafts.items():
        evs: list[RfqEvent] = d["evs"]
        kinds = {e.kind for e in evs}
        created = next((e for e in evs if e.kind is Kind.QUOTE_CREATED), None)
        accepted = [e for e in evs if e.kind is Kind.QUOTE_ACCEPTED]
        order_ids = tuple(sorted({e.order_id for e in evs if e.kind is Kind.QUOTE_EXECUTED and e.order_id}))
        own_fills = [f for o in order_ids for f in fills_by_order.get(o, ())]
        fill_conflict = any(f.fill_id in conflicting for f in own_fills)
        filled = (None if not own_fills or fill_conflict or any(f.contracts is None for f in own_fills)
                  else sum((f.contracts for f in own_fills), ZERO))
        rfq = rfqs.get(d["rfq_id"])
        created_at = created.at_utc if created else None
        peers = peers_of[(d["rfq_id"], d["maker"])]
        newer = [q for t, q in peers if q != qid and t is not None and created_at is not None and t > created_at]
        tied = [q for t, q in peers if q != qid and (t is None or created_at is None or t == created_at)]
        progressed = kinds & {Kind.QUOTE_ACCEPTED, Kind.QUOTE_CONFIRMED, Kind.QUOTE_EXECUTED}
        reasons: list[str] = []

        if len(accepted) > 1:
            state, reasons = QuoteState.UNKNOWN, ["MULTIPLE_ACCEPTANCES"]  # partial acceptance is C1
        elif fill_conflict:
            state, reasons = QuoteState.UNKNOWN, ["FILL_RECORD_CONFLICT"]
        elif Kind.QUOTE_CANCELLED in kinds and (kinds & {Kind.QUOTE_CONFIRMED, Kind.QUOTE_EXECUTED} or own_fills):
            state, reasons = QuoteState.UNKNOWN, ["CANCELLED_AND_BINDING_EVIDENCE_CONFLICT"]
        elif Kind.QUOTE_EXECUTED in kinds or own_fills:
            state = QuoteState.ORDERS_PLACED
        elif Kind.QUOTE_CONFIRMED in kinds:
            state = QuoteState.CONFIRMED
        elif Kind.QUOTE_CANCELLED in kinds:
            state = QuoteState.CANCELLED  # terminal; covers an accepted quote voided unconfirmed
        elif Kind.QUOTE_ACCEPTED in kinds:
            state = QuoteState.ACCEPTED
        elif newer:
            state, reasons = QuoteState.REPLACED, [f"REPLACED_BY:{sorted(newer)[0]}"]
        elif rfq is not None and rfq.open is False:
            state, reasons = QuoteState.RFQ_CLOSED_REASON_UNKNOWN, ["RFQ_CLOSED_NO_QUOTE_TERMINAL_STATUS"]
        elif created is not None:
            state = QuoteState.OPEN
        else:
            state, reasons = QuoteState.UNKNOWN, ["NO_QUOTE_CREATED_EVENT"]
        if tied and not progressed and state is QuoteState.OPEN:
            reasons.append("REPLACEMENT_ORDER_AMBIGUOUS")
        src = created or evs[0]
        acc = accepted[0] if len(accepted) == 1 else None
        quotes[qid] = QuoteView(
            quote_id=qid, rfq_id=d["rfq_id"], own=d["own"], on_own_rfq=d["on_own_rfq"], state=state,
            reasons=tuple(reasons), yes_bid=src.yes_bid, no_bid=src.no_bid,
            yes_contracts=src.yes_contracts_offered, no_contracts=src.no_contracts_offered,
            created_at_utc=created_at, accepted_side=acc.accepted_side if acc else None,
            accepted_received_at_utc=acc.received_at_utc if acc else None,
            contracts_accepted_notified=acc.contracts_accepted if acc else None,
            order_ids=order_ids, filled_contracts=filled)

    attributed = {o for q in quotes.values() for o in q.order_ids}
    contract_rfqs = [r for r in rfqs.values() if r.size_mode is SizeMode.CONTRACTS]
    cost_rfqs = [r for r in rfqs.values() if r.target_cost is not None]
    accepting = [q for q in quotes.values() if Kind.QUOTE_ACCEPTED in {e.kind for e in drafts[q.quote_id]["evs"]}]
    notified = [q.contracts_accepted_notified for q in accepting]
    usable_fills = [q.filled_contracts for q in quotes.values() if q.order_ids and q.filled_contracts is not None]
    return ObservationReport(
        status="OK", received_messages=str(len(received)), kept_messages=len(events), duplicate_messages=duplicates,
        undocumented_messages=tuple(sorted(undocumented)), malformed_messages=malformed,
        not_addressed_to_observer=foreign, rfqs=MappingProxyType(rfqs), quotes=MappingProxyType(quotes),
        requested_contracts_upper_bound=sum((r.requested_contracts for r in contract_rfqs), ZERO)
        if contract_rfqs else None,
        requested_target_cost_dollars=sum((r.target_cost for r in cost_rfqs), ZERO) if cost_rfqs else None,
        accepted_contracts_notified=(sum(notified, ZERO) if notified and all(n is not None for n in notified)
                                     else None),
        filled_contracts=None if conflicting or not usable_fills else sum(usable_fills, ZERO),
        unattributed_fills=sum(1 for fs in fills_by_id.values() if fs[0].order_id not in attributed),
        conflicting_fills=conflicting, seq_gaps=_seq_gaps(parsed),
    )


# --------------------------------------------------------------------------- quote currency


def _observation_problem(report: ObservationReport, at: datetime, observed_through_utc: Any,
                         max_age: timedelta) -> bool:
    through = parse_utc(observed_through_utc)
    return (report.status != "OK" or report.seq_gaps is None or report.seq_gaps > 0 or through is None
            or through > at or at - through > max_age)


def quote_is_current(quote_id: str, report: ObservationReport, *, now: datetime, observed_through_utc: Any,
                     max_age: timedelta) -> tuple[bool, str]:
    """Whether a quote is still a live object at `now`. A research fact, never permission to act.

    `observed_through_utc` is the caller's statement of how far the stream was received. Without
    it within `max_age` of `now`, and without gap-free sequence numbers, nothing is current.
    Replaced, cancelled, closed, lapsed or unknown quotes are never current and cannot be reused."""
    at = parse_utc(now)
    if at is None:
        raise RfqResearchError("now must be timezone-aware")
    if _observation_problem(report, at, observed_through_utc, max_age):
        return False, "OBSERVATION_STALE_OR_GAPPED"
    q = report.quotes.get(quote_id)
    if q is None:
        return False, "QUOTE_NOT_OBSERVED"
    rfq = report.rfqs.get(q.rfq_id)
    if q.state is QuoteState.ACCEPTED:
        tclass = None if rfq is None else rfq.timing_class
        if tclass is None or q.accepted_received_at_utc is None:
            return False, "ACCEPTED_CONFIRMATION_WINDOW_UNKNOWN"
        if at - q.accepted_received_at_utc > CONFIRMATION_WINDOW[tclass]:
            # Measured from our receipt (the message has no acceptance time): the venue's window may
            # have ended earlier. Documented as voided; nothing is released by it.
            return False, "CONFIRMATION_WINDOW_ELAPSED"
        return False, "ACCEPTED_AWAITING_CONFIRMATION"
    if q.state is not QuoteState.OPEN:
        return False, q.state.value
    if "REPLACEMENT_ORDER_AMBIGUOUS" in q.reasons:
        return False, "REPLACEMENT_ORDER_AMBIGUOUS"
    if rfq is None or rfq.open is not True:
        return False, "RFQ_NOT_KNOWN_OPEN"
    return True, "OPEN"


@dataclass(frozen=True)
class HypotheticalQuote:
    """A price we *would* have quoted, for research replay only. `state_version` identifies the
    information/game state it was priced on (opaque here; PR A's state contract fills it)."""

    rfq_id: str
    yes_bid: Decimal
    no_bid: Decimal
    state_version: str | None
    priced_at_utc: str


def hypothetical_check(h: HypotheticalQuote, report: ObservationReport, *, current_state_version: str | None,
                       now: datetime, max_age: timedelta, observed_through_utc: Any) -> tuple[str, ...]:
    """Every reason the hypothetical price is not usable, in order. Never empty: the last reason is
    always PARTICIPATION_NOT_AUTHORIZED. A changed or unknown state invalidates the price, and so
    does a stale or gapped view of the RFQ stream."""
    at = parse_utc(now)
    if at is None:
        raise RfqResearchError("now must be timezone-aware")
    out: list[str] = []
    if h.state_version is None or current_state_version is None:
        out.append("STATE_VERSION_UNKNOWN")
    elif h.state_version != current_state_version:
        out.append("STATE_CHANGED")
    priced = parse_utc(h.priced_at_utc)
    if priced is None or priced > at or at - priced > max_age:
        out.append("PRICE_STALE")
    if _observation_problem(report, at, observed_through_utc, max_age):
        out.append("OBSERVATION_STALE_OR_GAPPED")
    rfq = report.rfqs.get(h.rfq_id)
    if rfq is None or rfq.open is not True:
        out.append("RFQ_NOT_KNOWN_OPEN")
    yb, nb = _dec(h.yes_bid), _dec(h.no_bid)
    if yb is None or nb is None or yb < 0 or nb < 0 or yb >= 1 or nb >= 1 or (yb == 0 and nb == 0):
        out.append("PRICE_INVALID")
    elif yb + nb > 1:
        out.append("YES_PLUS_NO_ABOVE_ONE")  # documented: the venue rejects it
    if not KALSHI.execution_authorized:
        out.append("PARTICIPATION_NOT_AUTHORIZED")
    return tuple(out)


# --------------------------------------------------------------------------- sizing


@dataclass(frozen=True)
class SizeResult:
    mode: SizeMode
    contracts: Decimal | None
    principal: Decimal | None
    fee: Decimal | None  # None: unknown (FEE_UNSUPPORTED), never zero
    total_debit: Decimal | None
    status: str  # OK | FEE_UNSUPPORTED | BELOW_MIN_SIZE | INVALID
    derivation: str = "RECONSTRUCTED: 0.01-contract floor; the venue's own rounding is not documented"


def derive_contracts(target_cost: Decimal, price: Decimal, mode: SizeMode, *,
                     fee_for: Callable[[Decimal, Decimal], Decimal | None] | None = None) -> SizeResult:
    """The contract count a target-cost RFQ resolves to at one quoted price.

    Principal-only: target / price, fee charged on top. Fee-inclusive (the default mode): the
    largest count whose principal plus taker fee fits in the target, which needs a verified fee
    function (`fee_for(contracts, price)`); without one the count is FEE_UNSUPPORTED. A negative
    fee is unknown. A target too small for one 0.01-contract step is BELOW_MIN_SIZE."""
    t, p = _dec(target_cost), _dec(price)
    if mode is SizeMode.CONTRACTS:
        raise RfqResearchError("CONTRACTS-sized RFQs are not derived from a target cost")
    if t is None or p is None or t <= 0 or p <= 0 or p >= 1:
        return SizeResult(mode, None, None, None, None, "INVALID")
    cap = (t / p).quantize(CONTRACT_STEP, rounding=ROUND_FLOOR)
    if cap < CONTRACT_STEP:
        return SizeResult(mode, None, None, None, None, "BELOW_MIN_SIZE")
    if mode is SizeMode.TARGET_COST_PRINCIPAL_ONLY:
        fee = None if fee_for is None else _nonneg(fee_for(cap, p))
        principal = cap * p
        return SizeResult(mode, cap, principal, fee, None if fee is None else principal + fee,
                          "OK" if fee is not None else "FEE_UNSUPPORTED")
    if fee_for is None:
        return SizeResult(mode, None, None, None, None, "FEE_UNSUPPORTED")
    # Largest n (in 0.01-contract steps) with n*price + fee <= target; assumes the fee does not
    # fall as size grows. Binary search, so a large target cannot make this loop long.
    lo, hi, best = 1, int(cap / CONTRACT_STEP), None
    while lo <= hi:
        mid = (lo + hi) // 2
        c = mid * CONTRACT_STEP
        fee = _nonneg(fee_for(c, p))
        if fee is None:
            return SizeResult(mode, None, None, None, None, "FEE_UNSUPPORTED")
        if c * p + fee <= t:
            best, lo = (c, fee), mid + 1
        else:
            hi = mid - 1
    if best is None:
        return SizeResult(mode, None, None, None, None, "BELOW_MIN_SIZE")
    c, fee = best
    return SizeResult(mode, c, c * p, fee, c * p + fee, "OK")


# --------------------------------------------------------------------------- exposure and collateral
#
# This module derives each obligation's worst-case principal and maps RFQ lifecycle states onto the
# canonical `execution_ticket.ObligationState`. Reservation itself (held states, no netting, unknown
# stays unknown, the cash comparison) is delegated to `execution_ticket.reserve_simultaneous_obligations`.

# Conservative mapping. Only a quote's own observed cancellation frees anything.
OBLIGATION_STATE = MappingProxyType({
    QuoteState.OPEN: ObligationState.OUTSTANDING,
    QuoteState.ACCEPTED: ObligationState.OUTSTANDING,  # can still bind at the maker's confirmation
    QuoteState.CONFIRMED: ObligationState.BOUND,
    QuoteState.ORDERS_PLACED: ObligationState.BOUND,
    QuoteState.CANCELLED: ObligationState.RELEASED,
    QuoteState.REPLACED: ObligationState.CANCEL_REQUESTED,  # superseded, but no cancellation observed
    QuoteState.RFQ_CLOSED_REASON_UNKNOWN: ObligationState.UNKNOWN,
    QuoteState.UNKNOWN: ObligationState.UNKNOWN,
})


@dataclass(frozen=True)
class Obligation:
    """Worst-case principal an own quote or RFQ could require, before fees. `principal` None is
    unknown and fails closed; a negative or non-finite value is refused (as the canonical primitive
    refuses it). Fees are not included (FEE_UNSUPPORTED) unless the caller adds an allowance."""

    source_id: str
    rfq_id: str
    role: str  # QUOTER | REQUESTER
    state: QuoteState
    obligation_state: ObligationState
    principal: Decimal | None
    exchange_index: int | None
    legs: tuple[Leg, ...]
    market_ticker: str | None
    reason: str

    def __post_init__(self) -> None:
        v = self.principal
        if v is not None and (not isinstance(v, Decimal) or not v.is_finite() or v < 0):
            raise RfqResearchError(f"principal must be a finite, non-negative Decimal or None, not {v!r}")

    @property
    def exposure_keys(self) -> tuple[str, ...]:
        """Shared-exposure keys: each combo leg, or the market itself for a single-market RFQ."""
        if self.legs:
            return tuple(sorted({f"leg:{leg.market_ticker}:{leg.side}" for leg in self.legs}))
        return () if self.market_ticker is None else (f"market:{self.market_ticker}",)


def _max_known(values: Iterable[Decimal | None]) -> Decimal | None:
    vals = list(values)
    return None if not vals or any(v is None for v in vals) else max(vals)


def _times(price: Decimal | None, size: Decimal | None) -> Decimal | None:
    return None if price is None or size is None else price * size


def obligations(report: ObservationReport, *, exchange_index: Mapping[str, int] | None = None,
                include_released: bool = False) -> tuple[Obligation, ...]:
    """Worst-case principal per own quote (as maker) and per own RFQ with a quote that may bind
    (as requester), each with its canonical `ObligationState`. Only held obligations are returned
    unless `include_released`. A quote's own CANCELLED status maps to RELEASED; if any own fill is
    unattributed or conflicting it maps to UNKNOWN instead, so nothing is freed. A closed RFQ, a
    replacement, a lapsed confirmation window or a missing event frees nothing.

    Maker: it buys YES at yes_bid or NO at no_bid, for the full offered size; worst of the two.
    Requester: the mapping from `accepted_side` to the requester's own contract is not settled by
    the docs (REST vs FIX wording), so the worst of `bid` and `1 - bid` is reserved for the
    accepted side; when the side is not known from exactly one acceptance, the worst over both."""
    idx = exchange_index or {}
    release_blocked = report.unattributed_fills > 0 or bool(report.conflicting_fills)
    out: list[Obligation] = []
    for q in report.quotes.values():
        ostate = OBLIGATION_STATE[q.state]
        note = ""
        if ostate is ObligationState.RELEASED and release_blocked:
            ostate, note = ObligationState.UNKNOWN, "; release blocked by an unattributed or conflicting own fill"
        rfq = report.rfqs.get(q.rfq_id)
        legs = () if rfq is None else rfq.legs
        market = None if rfq is None else rfq.market_ticker
        ex = idx.get(market or "")
        rfq_size = None if rfq is None else rfq.requested_contracts
        size_y = q.yes_contracts if q.yes_contracts is not None else rfq_size
        size_n = q.no_contracts if q.no_contracts is not None else rfq_size
        if q.own:
            parts = [_times(bid, size) for bid, size in ((q.yes_bid, size_y), (q.no_bid, size_n))
                     if bid is None or bid != 0]  # a declined side cannot be accepted
            out.append(Obligation(q.quote_id, q.rfq_id, "QUOTER", q.state, ostate, _max_known(parts), ex, legs,
                                  market, "worst side at full offered size" + note))
        may_bind = q.state in REQUESTER_BOUND_STATES or (q.state in RELEASED_STATES and release_blocked)
        if q.on_own_rfq and may_bind:
            yb, nb = q.yes_bid, q.no_bid
            y = _times(None if yb is None else max(yb, ONE - yb), size_y)
            n = _times(None if nb is None else max(nb, ONE - nb), size_n)
            if q.accepted_side is not None and q.state is not QuoteState.UNKNOWN:
                principal, why = (y if q.accepted_side == "yes" else n), "accepted side: worst of bid and 1 - bid"
            else:
                principal, why = _max_known((y, n)), "accepted side unknown: worst over both sides"
            out.append(Obligation(f"{q.quote_id}:requester", q.rfq_id, "REQUESTER", q.state, ostate, principal,
                                  ex, legs, market, why + note))
    kept = [o for o in out if include_released or o.obligation_state in HELD_OBLIGATION_STATES]
    return tuple(sorted(kept, key=lambda o: o.source_id))


@dataclass(frozen=True)
class Reservation:
    """Per exchange index, the canonical reservation of every held obligation at once."""

    status: str  # OK | EXPOSURE_UNKNOWN | CASH_UNKNOWN | INSUFFICIENT_COLLATERAL | FEE_UNSUPPORTED
    by_index: Mapping[int, CanonicalReservation]
    unknown_shard: tuple[str, ...]  # obligations whose exchange index is unknown
    fee_unknown: tuple[str, ...]  # obligations with no fee allowance (principal only)


def reserve_simultaneous(obligs: Iterable[Obligation], available_by_index: Mapping[int, Decimal | None], *,
                         fee_allowance: Callable[[Obligation], Decimal | None] | None = None) -> Reservation:
    """A thin adapter onto `execution_ticket.reserve_simultaneous_obligations`, applied per exchange
    index because collateral is preallocated per shard (combos live on their own shard).

    Each obligation becomes a canonical `Obligation` whose worst case is principal plus the fee
    allowance. A missing fee allowance leaves principal only and makes the result FEE_UNSUPPORTED; a
    negative or non-finite allowance makes that worst case unknown. The canonical primitive decides
    what is held, never nets shared legs (its `by_key`), keeps unknown unknown and compares with cash.
    An unknown exchange index is EXPOSURE_UNKNOWN, and that obligation is added to every shard with an
    unknown worst case, so every shard's `required` (and any key it shares) is None too. Fee gaps are
    recorded only for held obligations."""
    groups: dict[int, list[CanonicalObligation]] = {}
    unknown_shard: list[Obligation] = []
    fee_unknown: list[str] = []
    for o in obligs:
        if o.exchange_index is None:
            unknown_shard.append(o)
            continue
        raw_fee = None if fee_allowance is None else fee_allowance(o)
        fee = _nonneg(raw_fee)
        if raw_fee is None and o.obligation_state in HELD_OBLIGATION_STATES:
            fee_unknown.append(o.source_id)  # a released obligation needs no fee allowance
        worst = (None if o.principal is None or (raw_fee is not None and fee is None)
                 else o.principal + (fee or ZERO))
        groups.setdefault(o.exchange_index, []).append(
            CanonicalObligation(o.source_id, o.obligation_state, worst, o.exposure_keys))
    # An obligation on an unknown shard could sit on any shard: it joins every shard's group with an
    # unknown worst case, so no shard's total or shared-key sum can look known without it.
    for group in groups.values():
        group.extend(CanonicalObligation(o.source_id, o.obligation_state, None, o.exposure_keys)
                     for o in unknown_shard)
    by_index: dict[int, CanonicalReservation] = {}
    asked: list[CanonicalReservation] = []
    for i, group in sorted(groups.items()):
        held = [c for c in group if c.state in HELD_OBLIGATION_STATES]
        if not held:  # nothing held on this shard: nothing to fit
            by_index[i] = reserve_simultaneous_obligations(tuple(group), available_cash=available_by_index.get(i))
            continue
        # The last held obligation is the canonical "candidate": allowed means all of them fit at once.
        rest = tuple(c for c in group if c is not held[-1])
        by_index[i] = reserve_simultaneous_obligations(rest, available_cash=available_by_index.get(i),
                                                       candidate=held[-1])
        asked.append(by_index[i])
    if unknown_shard or any(r.required is None for r in by_index.values()):
        status = "EXPOSURE_UNKNOWN"
    elif any(any(x.startswith("CASH_UNKNOWN") for x in r.reasons) for r in asked):
        status = "CASH_UNKNOWN"
    elif not all(r.new_risk_allowed for r in asked):
        status = "INSUFFICIENT_COLLATERAL"
    else:
        status = "FEE_UNSUPPORTED" if fee_unknown else "OK"
    return Reservation(status, MappingProxyType(by_index), tuple(sorted(o.source_id for o in unknown_shard)),
                       tuple(sorted(fee_unknown)))


# --------------------------------------------------------------------------- feasibility summary (for the Terminal)
#
# A compact, display-only summary of `docs/research/RFQ_FEASIBILITY_2026-09.md` §2 (the capability and
# observability matrix) and §6 (the decision and the owner decisions). `tests/test_rfq_feasibility_summary.py`
# keeps every row equal to the document's table, in order. It grants nothing and reads nothing.


class CapabilityState(str, Enum):
    DOCUMENTED = "DOCUMENTED"  # the documentation defines it (observable with the right access)
    PRIVATE = "PRIVATE"  # exists, but visible only to the parties or the venue: never to an outside observer
    UNAVAILABLE = "UNAVAILABLE"  # documented, but we cannot observe it under current authority (no credential)
    UNKNOWN = "UNKNOWN"  # not documented, conflicting, or unresolved


@dataclass(frozen=True)
class CapabilityRow:
    item: str  # the matrix row's name, exactly as in the document
    state: CapabilityState
    note: str


FEASIBILITY_DOCUMENT = "docs/research/RFQ_FEASIBILITY_2026-09.md"
FEASIBILITY_DECISION = "NARROW"
FEASIBILITY_MATRIX: tuple[CapabilityRow, ...] = (
    CapabilityRow("Request metadata", CapabilityState.UNAVAILABLE,
                  "broadcast on an authenticated channel; we hold no credential"),
    CapabilityRow("Combo definitions and legs", CapabilityState.DOCUMENTED,
                  "definitions are public reads (a new read scope, not authorized today)"),
    CapabilityRow("Authentication and actual entitlements", CapabilityState.UNKNOWN,
                  "whether a read-only key or a non-maker member can subscribe or quote"),
    CapabilityRow("Storage, training and derived-data rights", CapabilityState.UNKNOWN,
                  "which terms govern API data is unresolved"),
    CapabilityRow("Our quotes vs other makers' quotes", CapabilityState.PRIVATE,
                  "each quote is private between requester and maker; no competitor price is ever shown"),
    CapabilityRow("Acceptance and fill visibility", CapabilityState.PRIVATE,
                  "parties only; public block-trade flags are unattributed and unverified"),
    CapabilityRow("Native quantity and payout", CapabilityState.DOCUMENTED, "0.01-contract steps; $1 binary payout"),
    CapabilityRow("Fee-inclusive vs principal-only target size", CapabilityState.DOCUMENTED,
                  "an observer cannot see a target-cost RFQ's fee mode"),
    CapabilityRow("Full-request obligations and partial acceptance", CapabilityState.UNKNOWN,
                  "conflict C1: plan for full-size obligations"),
    CapabilityRow("Quote replacement and expiry", CapabilityState.DOCUMENTED, "durations are not documented"),
    CapabilityRow("Acceptance → maker confirmation → execution", CapabilityState.DOCUMENTED,
                  "binding at maker confirmation; execution is not a fill"),
    CapabilityRow("Timing classes and the binding point", CapabilityState.DOCUMENTED,
                  "30 s / 3 s confirmation (conflict C2)"),
    CapabilityRow("Collateral", CapabilityState.UNKNOWN, "when an open quote reserves collateral"),
    CapabilityRow("Common-leg exposure", CapabilityState.DOCUMENTED, "no netting is documented: treat as none"),
    CapabilityRow("Account attribution", CapabilityState.DOCUMENTED, "subaccounts; pseudonymous creator ids"),
    CapabilityRow("Outage, pause, cancel and unknown states", CapabilityState.UNKNOWN,
                  "RFQ behaviour during pauses is not documented"),
)
OWNER_DECISIONS: tuple[tuple[str, str], ...] = (
    ("D1", "Data rights: read the Developer Agreement signed in, and decide (adds RFQ-stream storage)."),
    ("D2", "Approve a narrowest-scope Kalshi credential for observe-only `communications`, plus a bounded census. "
           "Credential creation is not authorized today."),
    ("D3", "Add the RFQ questions to the Kalshi message (revision 3); sending stays owner-confirmed."),
    ("D4", "Approve a bounded public read of `is_block_trade` trades as a new read scope (useful only once C7 is "
           "answered)."),
    ("D5", "A research slot: RFQ empirical work would be a new family under #96."),
    ("D6", "Budget: $0 cash for D2 and D4; owner hours unpriced; VPS headroom checked first; no paid tier."),
)
