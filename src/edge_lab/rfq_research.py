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
- **Binding point.** Documented: once the maker confirms, neither party can withdraw. Before
  that the maker may let the confirmation window pass.
- **Order independence.** State is derived from the *set* of distinct events, so duplicates and
  out-of-order delivery give the same answer. Contradictory terminal evidence is UNKNOWN.
- **Conservative exposure.** An own quote or RFQ keeps its worst-case principal reserved until
  a documented terminal state is observed. Silence (a lapsed window, a missing event) releases
  nothing. Simultaneous obligations are summed; shared combo legs never share collateral.
- **Input bound.** The communications channel ignores market filtering, so the bound applies to
  every received message, before any local filter. Over the bound the whole batch is refused,
  never truncated.
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
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from .freshness import parse_utc
from .provenance import payload_sha256
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
    QUOTE_ACCEPTED = "quote_accepted"  # communications channel, parties only
    QUOTE_EXECUTED = "quote_executed"  # communications channel, parties only: orders placed, not fills
    # Not channel events. Fixture adapters for REST quote status (`confirmed`, `cancelled`) and for
    # the member's own fill records (`GET /portfolio/fills`, the `fill` channel).
    QUOTE_CONFIRMED = "quote_confirmed"
    QUOTE_CANCELLED = "quote_cancelled"
    FILL = "fill"


PARTY_ONLY = frozenset({Kind.QUOTE_CREATED, Kind.QUOTE_ACCEPTED, Kind.QUOTE_EXECUTED,
                        Kind.QUOTE_CONFIRMED, Kind.QUOTE_CANCELLED, Kind.FILL})


class QuoteState(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"  # requester accepted; the maker has not confirmed: not binding on the maker
    CONFIRMED = "CONFIRMED"  # binding: neither party can withdraw (documented)
    ORDERS_PLACED = "ORDERS_PLACED"  # `quote_executed`: orders entered, fills not established
    CANCELLED = "CANCELLED"
    REPLACED = "REPLACED"  # the same maker quoted this RFQ again later (documented replacement)
    RFQ_CLOSED = "RFQ_CLOSED"  # the RFQ was deleted/closed before any acceptance
    UNKNOWN = "UNKNOWN"  # contradictory or undocumented evidence


RELEASED_STATES = frozenset({QuoteState.CANCELLED, QuoteState.REPLACED, QuoteState.RFQ_CLOSED})


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


# --------------------------------------------------------------------------- events


@dataclass(frozen=True)
class Leg:
    event_ticker: str
    market_ticker: str
    side: str  # "yes" | "no"


@dataclass(frozen=True)
class RfqEvent:
    """One received message, normalised. `key` is content-derived (transport sid/seq/sending time
    excluded), so a redelivered message is the same event."""

    kind: Kind | None  # None: an undocumented message type (kept and counted, never used)
    raw_type: str
    key: str
    rfq_id: str | None
    quote_id: str | None
    rfq_creator_id: str | None
    quote_creator_id: str | None
    market_ticker: str | None
    at_utc: datetime | None
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


_TRANSPORT_FIELDS = ("sid", "seq", "sending_ts_ms")
_TIME_FIELDS = ("created_ts", "deleted_ts", "accepted_ts", "confirmed_ts", "executed_ts", "cancelled_ts",
                "created_time")


def parse_message(raw: Mapping[str, Any]) -> RfqEvent:
    """Normalise one documented message (`{"type": ..., "msg": {...}}`). Never raises on content:
    an undocumented type has `kind` None and a message missing its identifiers is `malformed`."""
    raw_type = str(raw.get("type", ""))
    msg = raw.get("msg") if isinstance(raw.get("msg"), Mapping) else {}
    try:
        kind: Kind | None = Kind(raw_type)
    except ValueError:
        kind = None
    key = payload_sha256({"type": raw_type, "msg": msg,
                          **{k: v for k, v in raw.items() if k not in _TRANSPORT_FIELDS + ("type", "msg")}})
    at = next((parse_utc(msg.get(f)) for f in _TIME_FIELDS if msg.get(f) is not None), None)
    is_rfq_kind = kind in (Kind.RFQ_CREATED, Kind.RFQ_DELETED)
    rfq_id = msg.get("id") if is_rfq_kind else msg.get("rfq_id")
    legs: list[Leg] = []
    malformed = False
    for leg in msg.get("mve_selected_legs") or ():
        if not isinstance(leg, Mapping) or leg.get("side") not in ("yes", "no") \
                or not leg.get("market_ticker") or not leg.get("event_ticker"):
            malformed = True
            continue
        legs.append(Leg(str(leg["event_ticker"]), str(leg["market_ticker"]), str(leg["side"])))
    excl = msg.get("target_cost_excludes_fees")
    event = RfqEvent(
        kind=kind, raw_type=raw_type, key=key,
        rfq_id=None if rfq_id is None else str(rfq_id),
        quote_id=None if msg.get("quote_id") is None else str(msg.get("quote_id")),
        rfq_creator_id=_s(msg.get("creator_id") if is_rfq_kind else msg.get("rfq_creator_id")),
        quote_creator_id=_s(msg.get("quote_creator_id")),
        market_ticker=_s(msg.get("market_ticker")), at_utc=at,
        contracts=_dec(msg.get("contracts_fp") if kind is not Kind.FILL else msg.get("count_fp")),
        target_cost=_dec(msg.get("target_cost_dollars", msg.get("rfq_target_cost_dollars"))),
        target_cost_excludes_fees=excl if isinstance(excl, bool) else None,
        legs=tuple(legs),
        yes_bid=_dec(msg.get("yes_bid_dollars")), no_bid=_dec(msg.get("no_bid_dollars")),
        yes_contracts_offered=_dec(msg.get("yes_contracts_offered_fp")),
        no_contracts_offered=_dec(msg.get("no_contracts_offered_fp")),
        accepted_side=msg.get("accepted_side") if msg.get("accepted_side") in ("yes", "no") else None,
        contracts_accepted=_dec(msg.get("contracts_accepted_fp")),
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
    accepted_side: str | None
    accepted_at_utc: datetime | None
    contracts_accepted_notified: Decimal | None
    order_ids: tuple[str, ...]
    filled_contracts: Decimal | None  # None: no fill record observed (not zero)


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
    received_messages: int  # every message received, before any local filter
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
    filled_contracts: Decimal | None = None  # own fills only; None when none were observed
    unattributed_fills: int = 0  # own fill records matching no observed quote_executed order id
    other_parties_fills: Visibility = Visibility.UNAVAILABLE
    competitor_quote_prices: Visibility = Visibility.UNAVAILABLE
    queue_rank: Visibility = Visibility.UNSUPPORTED  # RFQ quotes have no documented queue or rank


def _refused(status: str, received: int) -> ObservationReport:
    return ObservationReport(status=status, received_messages=received, kept_messages=0, duplicate_messages=0,
                             undocumented_messages=(), malformed_messages=0, not_addressed_to_observer=0,
                             requested_contracts_upper_bound=None, requested_target_cost_dollars=None,
                             accepted_contracts_notified=None, filled_contracts=None)


def observe(messages: Iterable[Mapping[str, Any]], observer: Observer, *, max_messages: int,
            keep: Callable[[RfqEvent], bool] | None = None,
            timing_class: Mapping[str, TimingClass] | None = None) -> ObservationReport:
    """Fold received messages into per-RFQ and per-quote views for `observer`.

    `max_messages` bounds everything received (the channel ignores market filtering), checked
    before `keep` filters locally. Over the bound the batch is refused whole. `timing_class`
    maps a market ticker to its documented class; a combo (MVE legs present) is always HVM."""
    if not isinstance(max_messages, int) or isinstance(max_messages, bool) or max_messages < 0:
        raise RfqResearchError("max_messages must be a non-negative whole number")
    received = list(messages)
    if len(received) > max_messages:
        return _refused("REFUSED_INPUT_BOUND", len(received))
    if not observer.authenticated:
        return _refused("REFUSED_NOT_AUTHENTICATED", len(received))

    seen: dict[str, RfqEvent] = {}
    duplicates = malformed = foreign = 0
    undocumented: list[str] = []
    for raw in received:
        event = parse_message(raw) if isinstance(raw, Mapping) else None
        if event is None:
            malformed += 1
            continue
        if event.kind is None:
            undocumented.append(event.raw_type)
            continue
        if event.malformed:
            malformed += 1
            continue
        if event.key in seen:
            duplicates += 1
            continue
        seen[event.key] = event
    # Sorted by content key: every later "first" choice is independent of arrival order.
    events = sorted((e for e in seen.values() if keep is None or keep(e)), key=lambda e: e.key)

    me = observer.comm_id
    rfq_events: dict[str, list[RfqEvent]] = {}
    quote_events: dict[str, list[RfqEvent]] = {}
    fills: list[RfqEvent] = []
    for e in events:
        if e.kind is Kind.FILL:
            fills.append(e)  # the member's own fill records only; matched to quotes by order id
        elif e.kind in (Kind.RFQ_CREATED, Kind.RFQ_DELETED):
            rfq_events.setdefault(e.rfq_id, []).append(e)
        else:
            quote_events.setdefault(e.quote_id, []).append(e)

    # Who created each RFQ, from any event that names it (the creator always sees their own id).
    rfq_creator: dict[str, str] = {}
    for e in events:
        if e.rfq_id and e.rfq_creator_id and e.rfq_creator_id != "0":
            rfq_creator.setdefault(e.rfq_id, e.rfq_creator_id)

    quotes: dict[str, QuoteView] = {}
    drafts: dict[str, dict[str, Any]] = {}
    for qid, evs in quote_events.items():
        rfq_id = next((e.rfq_id for e in evs if e.rfq_id), None)
        maker = next((e.quote_creator_id for e in evs if e.quote_creator_id), None)
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

    fills_by_order: dict[str, list[RfqEvent]] = {}
    for f in fills:
        fills_by_order.setdefault(f.order_id, []).append(f)

    # Replacement: a maker's later quote on the same RFQ replaces its earlier one (documented).
    latest: dict[tuple[str | None, str | None], list[tuple[datetime | None, str]]] = {}
    for qid, d in drafts.items():
        created_at = next((e.at_utc for e in d["evs"] if e.kind is Kind.QUOTE_CREATED), None)
        latest.setdefault((d["rfq_id"], d["maker"]), []).append((created_at, qid))

    for qid, d in drafts.items():
        evs: list[RfqEvent] = d["evs"]
        kinds = {e.kind for e in evs}
        created = next((e for e in evs if e.kind is Kind.QUOTE_CREATED), None)
        accepted = [e for e in evs if e.kind is Kind.QUOTE_ACCEPTED]
        executed = [e for e in evs if e.kind is Kind.QUOTE_EXECUTED]
        order_ids = tuple(sorted({e.order_id for e in executed if e.order_id}))
        own_fills = [f for o in order_ids for f in fills_by_order.get(o, ())]
        filled = sum((f.contracts for f in own_fills if f.contracts is not None), ZERO) if own_fills else None
        reasons: list[str] = []
        sides = {e.accepted_side for e in accepted if e.accepted_side}
        rfq = rfqs.get(d["rfq_id"])
        created_at = created.at_utc if created else None
        peers = latest[(d["rfq_id"], d["maker"])]
        newer = [q for t, q in peers if q != qid and t is not None and created_at is not None and t > created_at]
        tied = [q for t, q in peers if q != qid and (t is None or created_at is None or t == created_at)]
        progressed = kinds & {Kind.QUOTE_ACCEPTED, Kind.QUOTE_CONFIRMED, Kind.QUOTE_EXECUTED}

        if len(sides) > 1:
            state, reasons = QuoteState.UNKNOWN, ["CONTRADICTORY_ACCEPTED_SIDES"]
        elif Kind.QUOTE_CANCELLED in kinds and (kinds & {Kind.QUOTE_CONFIRMED, Kind.QUOTE_EXECUTED}):
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
            state, reasons = QuoteState.RFQ_CLOSED, ["RFQ_CLOSED_BEFORE_ACCEPTANCE"]
        elif created is not None:
            state = QuoteState.OPEN
        else:
            state, reasons = QuoteState.UNKNOWN, ["NO_QUOTE_CREATED_EVENT"]
        if tied and not progressed and state is QuoteState.OPEN:
            reasons.append("REPLACEMENT_ORDER_AMBIGUOUS")
        src = created or evs[0]
        acc = accepted[0] if accepted else None
        quotes[qid] = QuoteView(
            quote_id=qid, rfq_id=d["rfq_id"], own=d["own"], on_own_rfq=d["on_own_rfq"], state=state,
            reasons=tuple(reasons), yes_bid=src.yes_bid, no_bid=src.no_bid,
            yes_contracts=src.yes_contracts_offered, no_contracts=src.no_contracts_offered,
            created_at_utc=created_at, accepted_side=acc.accepted_side if acc else None,
            accepted_at_utc=min((e.at_utc for e in accepted if e.at_utc), default=None),
            contracts_accepted_notified=acc.contracts_accepted if acc else None,
            order_ids=order_ids, filled_contracts=filled)

    attributed = {o for q in quotes.values() for o in q.order_ids}
    contract_rfqs = [r for r in rfqs.values() if r.size_mode is SizeMode.CONTRACTS]
    cost_rfqs = [r for r in rfqs.values() if r.target_cost is not None]
    notified = [q.contracts_accepted_notified for q in quotes.values() if q.accepted_side]
    fill_counts = [q.filled_contracts for q in quotes.values() if q.filled_contracts is not None]
    return ObservationReport(
        status="OK", received_messages=len(received), kept_messages=len(events), duplicate_messages=duplicates,
        undocumented_messages=tuple(sorted(undocumented)), malformed_messages=malformed, not_addressed_to_observer=foreign,
        rfqs=MappingProxyType(rfqs), quotes=MappingProxyType(quotes),
        requested_contracts_upper_bound=sum((r.requested_contracts for r in contract_rfqs), ZERO)
        if contract_rfqs else None,
        requested_target_cost_dollars=sum((r.target_cost for r in cost_rfqs), ZERO) if cost_rfqs else None,
        accepted_contracts_notified=(sum(notified, ZERO) if notified and all(n is not None for n in notified)
                                     else None),
        filled_contracts=sum(fill_counts, ZERO) if fill_counts else None,
        unattributed_fills=sum(1 for f in fills if f.order_id not in attributed),
    )


# --------------------------------------------------------------------------- quote currency


def quote_is_current(quote_id: str, report: ObservationReport, *, now: datetime) -> tuple[bool, str]:
    """Whether a quote is still a live object at `now`. A research fact, never permission to act.
    Replaced, cancelled, closed, lapsed or unknown quotes are not current and cannot be reused."""
    at = parse_utc(now)
    if at is None:
        raise RfqResearchError("now must be timezone-aware")
    q = report.quotes.get(quote_id)
    if q is None:
        return False, "QUOTE_NOT_OBSERVED"
    rfq = report.rfqs.get(q.rfq_id)
    if q.state is QuoteState.ACCEPTED:
        tclass = None if rfq is None else rfq.timing_class
        if tclass is None or q.accepted_at_utc is None:
            return False, "ACCEPTED_CONFIRMATION_WINDOW_UNKNOWN"
        if at - q.accepted_at_utc > CONFIRMATION_WINDOW[tclass]:
            return False, "CONFIRMATION_WINDOW_ELAPSED"  # documented as voided; nothing is released by it
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
                       now: datetime, max_age: timedelta) -> tuple[str, ...]:
    """Every reason the hypothetical price is not usable, in order. Never empty: the last reason is
    always PARTICIPATION_NOT_AUTHORIZED. A changed or unknown state invalidates the price."""
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
    status: str  # OK | FEE_UNSUPPORTED | INVALID
    derivation: str = "RECONSTRUCTED: 0.01-contract floor; the venue's own rounding is not documented"


def derive_contracts(target_cost: Decimal, price: Decimal, mode: SizeMode, *,
                     fee_for: Callable[[Decimal, Decimal], Decimal | None] | None = None) -> SizeResult:
    """The contract count a target-cost RFQ resolves to at one quoted price.

    Principal-only: target / price, fee charged on top. Fee-inclusive (the default mode): the
    largest count whose principal plus taker fee fits in the target, which needs a verified fee
    function (`fee_for(contracts, price)`); without one the count is FEE_UNSUPPORTED."""
    t, p = _dec(target_cost), _dec(price)
    if mode is SizeMode.CONTRACTS:
        raise RfqResearchError("CONTRACTS-sized RFQs are not derived from a target cost")
    if t is None or p is None or t <= 0 or p <= 0 or p >= 1:
        return SizeResult(mode, None, None, None, None, "INVALID")
    cap = (t / p).quantize(CONTRACT_STEP, rounding=ROUND_FLOOR)
    if mode is SizeMode.TARGET_COST_PRINCIPAL_ONLY:
        fee = None if fee_for is None else _dec(fee_for(cap, p))
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
        fee = _dec(fee_for(c, p))
        if fee is None or fee < 0:
            return SizeResult(mode, None, None, None, None, "FEE_UNSUPPORTED")
        if c * p + fee <= t:
            best, lo = (c, fee), mid + 1
        else:
            hi = mid - 1
    if best is None:
        return SizeResult(mode, ZERO, ZERO, ZERO, ZERO, "OK")
    c, fee = best
    return SizeResult(mode, c, c * p, fee, c * p + fee, "OK")


# --------------------------------------------------------------------------- exposure and collateral


@dataclass(frozen=True)
class Obligation:
    """Worst-case principal an own quote or RFQ could require. `principal` None is unknown and
    fails closed. Fees are not included (FEE_UNSUPPORTED) unless the caller adds an allowance."""

    source_id: str
    rfq_id: str
    role: str  # QUOTER | REQUESTER
    state: QuoteState
    principal: Decimal | None
    exchange_index: int | None
    legs: tuple[Leg, ...]
    reason: str


def _max_known(values: Iterable[Decimal | None]) -> Decimal | None:
    vals = list(values)
    return None if not vals or any(v is None for v in vals) else max(vals)


def obligations(report: ObservationReport, *, exchange_index: Mapping[str, int] | None = None
                ) -> tuple[Obligation, ...]:
    """Worst-case principal per own quote (as maker) and per own RFQ with an accepted quote (as
    requester). Released only in a documented terminal state (cancelled, replaced, RFQ closed
    before acceptance). A lapsed confirmation window, a missing event or UNKNOWN releases nothing.

    Maker: it buys YES at yes_bid or NO at no_bid, for the full offered size; worst of the two.
    An own quote on an RFQ that closed with no acceptance seen is released: a maker quote cannot
    bind without the maker's own confirmation. A fill releases nothing (settlement is not modelled).
    Requester: the mapping from `accepted_side` to the requester's own contract is not settled by
    the docs (REST vs FIX wording), so the worst of `bid` and `1 - bid` is reserved."""
    idx = exchange_index or {}
    out: list[Obligation] = []
    for q in report.quotes.values():
        if q.state in RELEASED_STATES:
            continue
        rfq = report.rfqs.get(q.rfq_id)
        legs = () if rfq is None else rfq.legs
        market = None if rfq is None else rfq.market_ticker
        ex = idx.get(market or "")
        rfq_size = None if rfq is None else rfq.requested_contracts
        size_y = q.yes_contracts if q.yes_contracts is not None else rfq_size
        size_n = q.no_contracts if q.no_contracts is not None else rfq_size
        if q.own:
            parts = []
            for bid, size in ((q.yes_bid, size_y), (q.no_bid, size_n)):
                if bid is not None and bid == 0:
                    continue  # a declined side cannot be accepted
                parts.append(None if bid is None or size is None else bid * size)
            out.append(Obligation(q.quote_id, q.rfq_id, "QUOTER", q.state, _max_known(parts), ex, legs,
                                  "worst side at full offered size"))
        if q.on_own_rfq and q.accepted_side:
            bid = q.yes_bid if q.accepted_side == "yes" else q.no_bid
            size = size_y if q.accepted_side == "yes" else size_n
            principal = None if bid is None or size is None else max(bid, ONE - bid) * size
            out.append(Obligation(f"{q.quote_id}:requester", q.rfq_id, "REQUESTER", q.state, principal, ex, legs,
                                  "accepted-side mapping unresolved: worst of bid and 1 - bid"))
    return tuple(sorted(out, key=lambda o: o.source_id))


@dataclass(frozen=True)
class Reservation:
    status: str  # OK | INSUFFICIENT_COLLATERAL | EXPOSURE_UNKNOWN | FEE_UNSUPPORTED
    required_by_index: Mapping[int, Decimal]
    shortfalls: Mapping[int, Decimal]
    unknown: tuple[str, ...]
    common_legs: Mapping[tuple[str, str], tuple[str, ...]]  # (market, side) -> obligations using it


def reserve_simultaneous(obligs: Iterable[Obligation], available_by_index: Mapping[int, Decimal], *,
                         fee_allowance: Callable[[Obligation], Decimal | None] | None = None) -> Reservation:
    """Can every obligation be met at once? Obligations are summed per exchange index (collateral
    is preallocated per shard; combos live on their own shard). Nothing is netted: two quotes that
    share a combo leg each keep their full reservation, and the shared leg is reported."""
    items = list(obligs)
    required: dict[int, Decimal] = {}
    unknown: list[str] = []
    fee_missing = False
    legs: dict[tuple[str, str], list[str]] = {}
    for o in items:
        for leg in o.legs:
            legs.setdefault((leg.market_ticker, leg.side), []).append(o.source_id)
        if o.principal is None or o.exchange_index is None:
            unknown.append(o.source_id)
            continue
        fee = None if fee_allowance is None else _dec(fee_allowance(o))
        if fee is None:
            fee_missing = True
        required[o.exchange_index] = required.get(o.exchange_index, ZERO) + o.principal + (fee or ZERO)
    shortfalls = {i: need - (_dec(available_by_index.get(i)) or ZERO) for i, need in required.items()
                  if need > (_dec(available_by_index.get(i)) or ZERO)}
    status = ("EXPOSURE_UNKNOWN" if unknown else "INSUFFICIENT_COLLATERAL" if shortfalls
              else "FEE_UNSUPPORTED" if fee_missing else "OK")
    return Reservation(status, MappingProxyType(required), MappingProxyType(shortfalls), tuple(sorted(unknown)),
                       MappingProxyType({k: tuple(sorted(v)) for k, v in legs.items() if len(v) > 1}))
