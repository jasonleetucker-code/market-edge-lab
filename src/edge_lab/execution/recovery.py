"""Recovery for a future private order and fill stream (#160 package J). Pure; offline; FIXTURE only.

No stream exists yet: a stream transport is future work that needs the owner's explicit credential, source and budget
approval. This module is the model such a transport will feed. It opens nothing, reads no clock and stores nothing:
every function takes an immutable `RecoveryState` and returns a new one. The caller (the orchestrator) holds the
current state and supplies the items in arrival order.

**Items.** A `StreamMessage` carries its subscription id (`sid`), its sequence number (`seq`), its channel, one typed
event (`OrderUpdate` or `FillEvent`) and four clocks (`Clocks`): the venue's event time, the source's own stamp, the
send time and our receipt time. Only receipt is required. The others stay None when unknown and are never filled in
from one another. `SubscriptionOpened`, `ConnectionLost` and `BookObservation` (a top of book, unsequenced here; a
public book stream's own sequencing belongs to its reconstructor) complete the vocabulary.

**Sequence scope.** `seq` is judged per `sid`, across every market the subscription carries (STR-02 is UNKNOWN; this
is the conservative reading). A new `sid` starts a new sequence scope. Per message:
- the same (sid, seq) again with the same content is a duplicate, ignored and counted;
- the same (sid, seq) with different content is a CONFLICTING_DUPLICATE;
- a seq at or below the last one that cannot be matched is OUT_OF_ORDER (there is no reorder buffer);
- a seq more than one past the last one, or a first seq other than `first_seq`, is a SEQUENCE_GAP;
- a message on a retired sid is stale: ignored for state, but its market is still invalidated (conservative);
- a message on a sid never opened is an UNKNOWN_SUBSCRIPTION.

**Quarantine.** An anomaly quarantines the state that depends on the stream: the whole account for anything that
can hide a private message of any market (gaps, conflicts, reconnects, rate overruns, clock anomalies), one market
for a market-local contradiction (a corrected or conflicting fill, an order count that goes backwards, a REST
disagreement). Each quarantine has the earliest read start that can prove it (`not_before_utc`). Only `prove` clears
one, with a COMPLETE `account.reconcile_account` of the same account scope whose read started at or after that time:
the REST read began after the anomaly, so it reflects everything the stream may have hidden. A quarantine is never
cleared by later stream messages, by time passing or by a reconnect.

**Reconnects are not cancellations.** `ConnectionLost` and a replacing `SubscriptionOpened` retire subscriptions and
quarantine the account (messages may have been missed: a REST reconciliation is required). They change no order:
nothing here, or in the orchestrator, treats a lost stream as a cancelled order (STR-05). A new subscription with no
predecessor still needs a REST baseline (BASELINE_REQUIRED) before its state is usable.

**Clocks.** Receipt time going backwards (RECEIPT_ORDER), a source or send stamp going backwards while seq advances
(SOURCE_ORDER), and an event, source or send stamp later than our receipt by more than `max_clock_skew` (CLOCK_SKEW) all
quarantine the account. Nothing is re-dated: no source time is substituted for a missing one, and nothing earlier is
corrected backwards. An order update whose cumulative fill count is lower than one already seen keeps the higher
count and quarantines the market (REGRESSION).

**Rate bounds count incoming traffic**: every item received (duplicates, stale and refused ones included) enters a
sliding window by receipt time, and opened subscriptions a second one. Overruns quarantine the account
(RATE_EXCEEDED, RECONNECT_STORM) until a read that starts after the window has passed. Retained state is bounded
separately (`dedupe_window`, `max_tracked`); exceeding `max_tracked` quarantines rather than forgets silently.

**Invalidation.** Every relevant change gives its market a new epoch (the next value of a state-wide counter, never
reused): a fill, an order update that changes status or counts, a correction or conflict, and a book move beyond
`book_jump`. Account-wide quarantines bump the account epoch. Market epochs are pruned at each proof (bounded state);
a decision whose marks predate the proof then sees its market as changed, never as unchanged.
A caller takes `marks(state)` when it starts deciding and asks `decision_problems(state, market, marks)` before it acts:
any change since the marks, any covering quarantine, or a missing required subscription drops the decision until it is
re-evaluated from fresh evidence.

**REST/stream disagreement.** At a proof, every tracked order the stream reported before the read started must agree
with the COMPLETE REST listing: the order exists, its fill count is not below the stream's, and every fill id the
stream delivered is listed. Otherwise the market stays quarantined (DISAGREEMENT) and a finding is returned. REST
ahead of the stream is reported (REST_AHEAD_OF_STREAM) and REST wins: it is either stream latency or a lost message,
and only the sequence rules can tell the two apart.

Kalshi's private stream is undocumented in the conformance pack (`kalshi-ordinary-v0` excludes WebSockets), so every
venue fact this model would need is UNKNOWN (`STREAM_FACTS`). Nothing here relies on one of them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Union

from . import account as acct
from .model import AccountScope, canonical_json, exact_decimal, parse_utc_text, sha256_text, utc_text

STREAM_SCHEMA = "edge-lab-private-stream/1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,199}")


@dataclass(frozen=True)
class StreamFact:
    """A venue fact this model would need, its status and what the model does instead of relying on it."""

    id: str
    question: str
    support: str
    instead: str


STREAM_FACTS = (
    StreamFact("STR-01", "channel names and payload fields of the private order and fill stream", "UNKNOWN",
               "typed StreamMessage fields only; a future adapter maps the venue payload after DEMO_OBSERVED evidence"),
    StreamFact("STR-02", "whether seq counts per subscription across markets or per market", "UNKNOWN",
               "per subscription across every market it carries; a gap quarantines the whole account"),
    StreamFact("STR-03", "the first seq of a new subscription", "UNKNOWN",
               "RecoveryConfig.first_seq (default 1); None accepts any first seq and is weaker"),
    StreamFact("STR-04", "whether messages missed during a disconnect are replayed after a reconnect", "UNKNOWN",
               "never assumed: every new subscription needs a REST proof"),
    StreamFact("STR-05", "whether a dropped connection cancels resting orders", "UNKNOWN",
               "never assumed: a reconnect changes no order state; only a REST read does"),
    StreamFact("STR-06", "which clocks a private message carries (event, source, send)", "UNKNOWN",
               "each clock is optional and never substituted for another"),
    StreamFact("STR-07", "whether and how a corrected or busted fill is delivered", "UNKNOWN",
               "an explicit correction, or a conflicting re-delivery, quarantines the market until a REST proof"),
    StreamFact("STR-08", "message rate and burst limits of the private channels", "UNKNOWN",
               "RecoveryConfig bounds are provisional placeholders, not venue facts"),
    StreamFact("STR-09", "whether private channels carry a heartbeat", "UNKNOWN",
               "silence proves nothing; liveness comes only from the transport's ConnectionLost"),
)


class Channel(str, Enum):
    ORDERS = "ORDERS"  # our order updates
    FILLS = "FILLS"  # our fills


class Reason(str, Enum):
    """Why dependent state is quarantined."""

    BASELINE_REQUIRED = "BASELINE_REQUIRED"  # a subscription opened: no REST read after it yet
    RECONNECTED = "RECONNECTED"  # a subscription replaced a live one: messages in between may be lost
    CONNECTION_LOST = "CONNECTION_LOST"
    SEQUENCE_GAP = "SEQUENCE_GAP"
    CONFLICTING_DUPLICATE = "CONFLICTING_DUPLICATE"  # one (sid, seq), two contents
    OUT_OF_ORDER = "OUT_OF_ORDER"  # a seq at or below the last one that cannot be matched
    UNKNOWN_SUBSCRIPTION = "UNKNOWN_SUBSCRIPTION"
    CHANNEL_MISMATCH = "CHANNEL_MISMATCH"
    SID_REUSED = "SID_REUSED"
    RECEIPT_ORDER = "RECEIPT_ORDER"  # our receipt clock went backwards
    SOURCE_ORDER = "SOURCE_ORDER"  # a source or send stamp went backwards while seq advanced
    CLOCK_SKEW = "CLOCK_SKEW"  # a source or send stamp later than our receipt
    RATE_EXCEEDED = "RATE_EXCEEDED"
    RECONNECT_STORM = "RECONNECT_STORM"
    EVENT_CONFLICT = "EVENT_CONFLICT"  # one fill id, two contents, no correction declared
    CORRECTED_EVENT = "CORRECTED_EVENT"
    REGRESSION = "REGRESSION"  # a cumulative count went backwards
    DISAGREEMENT = "DISAGREEMENT"  # a COMPLETE REST read contradicts what the stream delivered before it
    TOO_MANY_TRACKED = "TOO_MANY_TRACKED"
    BACKLOG = "BACKLOG"  # the caller could not drain everything the source had
    SOURCE_FAILED = "SOURCE_FAILED"  # the caller's source raised or returned something unusable


class Applied(str, Enum):
    """What happened to one item."""

    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"  # a known fill re-delivered under a new seq (sequenced, not re-counted)
    STALE_SUBSCRIPTION = "STALE_SUBSCRIPTION"
    CORRECTION = "CORRECTION"
    QUARANTINED = "QUARANTINED"  # not applied: the item itself is the anomaly
    OPENED = "OPENED"
    DISCONNECTED = "DISCONNECTED"
    BOOK = "BOOK"


def _time(name: str, value: object, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be ISO-8601 text")
    return utc_text(parse_utc_text(value))


def _ident(name: str, value: object) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{name} must be a short identifier, not {value!r}")
    return value


def _count(name: str, value: object, *, positive: bool = False) -> Decimal:
    d = exact_decimal(value, name=name)
    if d < 0 or (positive and d == 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'non-negative'}")
    return d


def _price(name: str, value: object) -> Decimal | None:
    if value is None:
        return None
    d = exact_decimal(value, name=name)
    if not Decimal(0) <= d <= Decimal(1):
        raise ValueError(f"{name} must be a price in dollars, 0 to 1")
    return d


def _int(name: str, value: object, low: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise ValueError(f"{name} must be an int >= {low}")
    return value


# ---------------------------------------------------------------------------------------------- items


@dataclass(frozen=True)
class Clocks:
    """The four clocks of one item. None is unknown and is never filled in from another clock."""

    received_at_utc: str  # our receipt
    event_at_utc: str | None = None  # when the venue says the event happened
    source_at_utc: str | None = None  # the source's own stamp on the message
    sent_at_utc: str | None = None  # when the frame was sent

    def __post_init__(self) -> None:
        object.__setattr__(self, "received_at_utc", _time("received_at_utc", self.received_at_utc))
        for name in ("event_at_utc", "source_at_utc", "sent_at_utc"):
            object.__setattr__(self, name, _time(name, getattr(self, name), optional=True))


@dataclass(frozen=True)
class OrderUpdate:
    """One order's state as the stream reports it. Counts are cumulative."""

    order_id: str
    market_ticker: str
    status: str
    fill_count: Decimal
    remaining_count: Decimal
    client_order_id: str | None = None

    def __post_init__(self) -> None:
        _ident("order_id", self.order_id)
        _ident("market_ticker", self.market_ticker)
        _ident("status", self.status)
        if self.client_order_id is not None:
            _ident("client_order_id", self.client_order_id)
        object.__setattr__(self, "fill_count", _count("fill_count", self.fill_count))
        object.__setattr__(self, "remaining_count", _count("remaining_count", self.remaining_count))

    def body(self) -> dict:
        return {"kind": "ORDER", "order_id": self.order_id, "market_ticker": self.market_ticker,
                "status": self.status, "fill_count": self.fill_count, "remaining_count": self.remaining_count,
                "client_order_id": self.client_order_id}


@dataclass(frozen=True)
class FillEvent:
    """One fill of one of our orders."""

    fill_id: str
    order_id: str
    market_ticker: str
    count: Decimal
    yes_price: Decimal

    def __post_init__(self) -> None:
        _ident("fill_id", self.fill_id)
        _ident("order_id", self.order_id)
        _ident("market_ticker", self.market_ticker)
        object.__setattr__(self, "count", _count("count", self.count, positive=True))
        object.__setattr__(self, "yes_price", _price("yes_price", self.yes_price))
        if self.yes_price is None:
            raise ValueError("yes_price is required")

    def body(self) -> dict:
        return {"kind": "FILL", "fill_id": self.fill_id, "order_id": self.order_id,
                "market_ticker": self.market_ticker, "count": self.count, "yes_price": self.yes_price}


Event = Union[OrderUpdate, FillEvent]
_CHANNEL_EVENT = MappingProxyType({Channel.ORDERS: OrderUpdate, Channel.FILLS: FillEvent})


@dataclass(frozen=True)
class StreamMessage:
    sid: int
    seq: int
    channel: Channel
    event: Event
    clocks: Clocks
    corrects_event_id: str | None = None  # this message corrects an earlier event (a fill id)
    schema: str = STREAM_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != STREAM_SCHEMA:
            raise ValueError(f"unknown stream schema {self.schema!r}")
        _int("sid", self.sid, 1)
        _int("seq", self.seq, 0)
        if not isinstance(self.channel, Channel) or not isinstance(self.clocks, Clocks):
            raise ValueError("channel must be a Channel and clocks a Clocks")
        if not isinstance(self.event, _CHANNEL_EVENT[self.channel]):
            raise ValueError(f"a {self.channel.value} message carries a {_CHANNEL_EVENT[self.channel].__name__}")
        if self.corrects_event_id is not None:
            _ident("corrects_event_id", self.corrects_event_id)

    @property
    def market_ticker(self) -> str:
        return self.event.market_ticker

    def digest(self) -> str:
        """The content (clocks excluded: a re-delivered copy has another receipt time)."""
        return sha256_text(canonical_json({"sid": self.sid, "seq": self.seq, "channel": self.channel,
                                           "event": self.event.body(), "corrects": self.corrects_event_id}))

    def event_digest(self) -> str:
        return sha256_text(canonical_json({"event": self.event.body(), "corrects": self.corrects_event_id}))


@dataclass(frozen=True)
class SubscriptionOpened:
    """The venue confirmed a subscription; `at_utc` is our receipt of that confirmation."""

    sid: int
    channel: Channel
    at_utc: str

    def __post_init__(self) -> None:
        _int("sid", self.sid, 1)
        if not isinstance(self.channel, Channel):
            raise ValueError("channel must be a Channel")
        object.__setattr__(self, "at_utc", _time("at_utc", self.at_utc))


@dataclass(frozen=True)
class ConnectionLost:
    at_utc: str
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "at_utc", _time("at_utc", self.at_utc))
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("a reason is required")


@dataclass(frozen=True)
class BookObservation:
    """A market's best YES bid and ask (dollars; None: that side is empty or unknown)."""

    market_ticker: str
    yes_bid: Decimal | None
    yes_ask: Decimal | None
    clocks: Clocks

    def __post_init__(self) -> None:
        _ident("market_ticker", self.market_ticker)
        object.__setattr__(self, "yes_bid", _price("yes_bid", self.yes_bid))
        object.__setattr__(self, "yes_ask", _price("yes_ask", self.yes_ask))
        if not isinstance(self.clocks, Clocks):
            raise ValueError("clocks must be a Clocks")


StreamItem = Union[StreamMessage, SubscriptionOpened, ConnectionLost, BookObservation]


# ---------------------------------------------------------------------------------------------- configuration


@dataclass(frozen=True)
class RecoveryConfig:
    """Bounds and thresholds. Every default is a provisional placeholder (STR-08), not a venue fact."""

    max_items_per_window: int = 500  # incoming items of every kind, per `rate_window`
    rate_window: timedelta = timedelta(seconds=1)
    max_opens_per_window: int = 6  # subscriptions opened per `reconnect_window` (one connect opens one per channel)
    reconnect_window: timedelta = timedelta(minutes=5)
    max_clock_skew: timedelta = timedelta(seconds=5)
    book_jump: Decimal = Decimal("0.02")  # a best price moving by more than this invalidates its market
    first_seq: int | None = 1  # STR-03 is UNKNOWN; None accepts any first seq (weaker)
    dedupe_window: int = 1024  # (sid, seq) and fill ids kept for duplicate and conflict detection
    max_tracked: int = 1000  # markets, books and orders each
    max_items_per_drain: int = 500  # what the orchestrator drains at once
    required_channels: frozenset = frozenset(Channel)

    def __post_init__(self) -> None:
        for name in ("max_items_per_window", "max_opens_per_window", "dedupe_window", "max_tracked",
                     "max_items_per_drain"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1_000_000:
                raise ValueError(f"{name} must be an int in 1-1000000")
        for name in ("rate_window", "reconnect_window", "max_clock_skew"):
            if not isinstance(getattr(self, name), timedelta) or getattr(self, name) <= timedelta(0):
                raise ValueError(f"{name} must be a positive timedelta")
        object.__setattr__(self, "book_jump", exact_decimal(self.book_jump, name="book_jump"))
        if self.book_jump <= 0:
            raise ValueError("book_jump must be positive")
        if self.first_seq is not None:
            _int("first_seq", self.first_seq, 0)
        if not isinstance(self.required_channels, frozenset) or not self.required_channels or not all(
                isinstance(c, Channel) for c in self.required_channels):
            raise ValueError("required_channels must be a non-empty frozenset of Channel")


# ---------------------------------------------------------------------------------------------- state


@dataclass(frozen=True)
class Subscription:
    sid: int
    channel: Channel
    opened_at_utc: str
    last_seq: int | None = None
    last_source_utc: str | None = None
    last_sent_utc: str | None = None


@dataclass(frozen=True)
class Quarantine:
    reason: Reason
    market_ticker: str | None  # None: the whole account
    since_utc: str
    not_before_utc: str  # the earliest REST read start that can prove it
    detail: str


@dataclass(frozen=True)
class MarketMark:
    market_ticker: str
    epoch: int
    reason: str
    at_utc: str


@dataclass(frozen=True)
class TrackedOrder:
    """What the stream said about one order since the last proof. REST rebases it at every proof."""

    order_id: str
    market_ticker: str
    filled: Decimal | None  # the highest cumulative fill count an order update reported
    status: str | None
    remaining: Decimal | None
    fill_ids: tuple[str, ...]
    last_received_utc: str


@dataclass(frozen=True)
class Book:
    market_ticker: str
    yes_bid: Decimal | None
    yes_ask: Decimal | None
    received_at_utc: str


@dataclass(frozen=True)
class RecoveryState:
    config: RecoveryConfig
    subscriptions: tuple[Subscription, ...] = ()  # active
    retired: tuple[int, ...] = ()  # sids no longer active (most recent `dedupe_window`)
    quarantines: tuple[Quarantine, ...] = ()
    marks: tuple[MarketMark, ...] = ()
    account_epoch: int = 0
    account_reason: str = ""
    orders: tuple[TrackedOrder, ...] = ()
    books: tuple[Book, ...] = ()
    recent: tuple[tuple[int, int, str], ...] = ()  # (sid, seq, digest)
    events: tuple[tuple[str, str], ...] = ()  # (fill id, event digest)
    receipts: tuple[str, ...] = ()  # recent receipt times (incoming traffic)
    opens: tuple[str, ...] = ()  # recent subscription opens
    last_receipt_utc: str | None = None
    incoming: int = 0
    counts: tuple[tuple[str, int], ...] = ()
    proven_at_utc: str | None = None  # the read start of the last proof
    changes: int = 0  # every market change takes the next value as its market's epoch

    @property
    def channels(self) -> frozenset:
        return frozenset(s.channel for s in self.subscriptions)

    @property
    def connected(self) -> bool:
        return self.config.required_channels <= self.channels

    @property
    def reconciliation_required(self) -> bool:
        """Missing or doubtful private messages: only a COMPLETE REST reconciliation (`prove`) clears this."""
        return bool(self.quarantines)


@dataclass(frozen=True)
class Step:
    state: RecoveryState
    applied: Applied
    raised: tuple[Reason, ...]  # quarantines this item raised or extended
    detail: str = ""


@dataclass(frozen=True)
class Marks:
    """The epochs at the moment a caller started deciding."""

    account_epoch: int
    epochs: Mapping[str, int]


@dataclass(frozen=True)
class Finding:
    kind: str  # DISAGREEMENT or REST_AHEAD_OF_STREAM
    market_ticker: str
    order_id: str
    detail: str


@dataclass(frozen=True)
class Proof:
    state: RecoveryState
    proven: bool
    reason: str | None  # why nothing was proven
    read_started_utc: str | None
    cleared: tuple[Quarantine, ...]
    findings: tuple[Finding, ...]


def initial(config: RecoveryConfig) -> RecoveryState:
    """No subscription yet: not connected, so nothing that depends on the stream is usable."""
    if not isinstance(config, RecoveryConfig):
        raise ValueError("config must be a RecoveryConfig")
    return RecoveryState(config)


# ---------------------------------------------------------------------------------------------- internals


def _later(a: str, b: str) -> str:
    return a if parse_utc_text(a) >= parse_utc_text(b) else b


def _plus(at: str, delta: timedelta) -> str:
    return utc_text(parse_utc_text(at) + delta)


def _bump_count(st: RecoveryState, applied: Applied) -> RecoveryState:
    counts = dict(st.counts)
    counts[applied.value] = counts.get(applied.value, 0) + 1
    return replace(st, counts=tuple(sorted(counts.items())))


def _quarantine(st: RecoveryState, reason: Reason, market: str | None, since: str, not_before: str,
                detail: str) -> RecoveryState:
    """Add a quarantine, or widen the one with the same reason and scope (earliest since, latest not-before). Past
    `max_tracked` quarantined markets, a new market's quarantine covers the whole account instead (bounded state)."""
    if market is not None and market not in {q.market_ticker for q in st.quarantines} and len(
            {q.market_ticker for q in st.quarantines if q.market_ticker is not None}) >= st.config.max_tracked:
        market, detail = None, f"{market}: {detail}"
    out, merged = [], False
    for q in st.quarantines:
        if q.reason is reason and q.market_ticker == market:
            since_kept = since if parse_utc_text(since) < parse_utc_text(q.since_utc) else q.since_utc
            q = replace(q, since_utc=since_kept, not_before_utc=_later(q.not_before_utc, not_before),
                        detail=detail[:300])
            merged = True
        out.append(q)
    if not merged:
        out.append(Quarantine(reason, market, since, not_before, detail[:300]))
    st = replace(st, quarantines=tuple(out))
    if market is None:
        return replace(st, account_epoch=st.account_epoch + 1, account_reason=f"{reason.value}: {detail}"[:300])
    return _bump(st, market, f"{reason.value}: {detail}", since)


def _bump(st: RecoveryState, market: str, reason: str, at: str) -> RecoveryState:
    """A relevant change on `market`: its epoch moves, so a decision taken before it is invalid."""
    marks = {m.market_ticker: m for m in st.marks}
    old = marks.get(market)
    if old is None and len(marks) >= st.config.max_tracked:
        return _quarantine(st, Reason.TOO_MANY_TRACKED, None, at, at, f"more than {st.config.max_tracked} markets")
    changes = st.changes + 1  # a state-wide counter: an epoch value is never reused, even after marks are pruned
    marks[market] = MarketMark(market, changes, reason[:300], at)
    return replace(st, marks=tuple(marks[k] for k in sorted(marks)), changes=changes)


def _incoming(st: RecoveryState, received: str) -> tuple[RecoveryState, list[Reason]]:
    """Count one incoming item against the rate bound, and check our receipt clock's order."""
    cfg, raised = st.config, []
    at = parse_utc_text(received)
    receipts = (st.receipts + (received,))[-(cfg.max_items_per_window + 1):]
    start, n = at - cfg.rate_window, 0
    for t in reversed(receipts):
        if parse_utc_text(t) <= start:
            break
        n += 1
    st = replace(st, receipts=receipts[-cfg.max_items_per_window:], incoming=st.incoming + 1)
    if n > cfg.max_items_per_window:
        st = _quarantine(st, Reason.RATE_EXCEEDED, None, received, _plus(received, cfg.rate_window),
                         f"{n} items within {cfg.rate_window.total_seconds()}s")
        raised.append(Reason.RATE_EXCEEDED)
    if st.last_receipt_utc is not None and at < parse_utc_text(st.last_receipt_utc):
        st = _quarantine(st, Reason.RECEIPT_ORDER, None, received, st.last_receipt_utc,
                         f"received at {received}, after an item received at {st.last_receipt_utc}")
        raised.append(Reason.RECEIPT_ORDER)
    else:
        st = replace(st, last_receipt_utc=received)
    return st, raised


def _done(st: RecoveryState, applied: Applied, raised: list[Reason], detail: str = "") -> Step:
    return Step(_bump_count(st, applied), applied, tuple(raised), detail[:300])


def _orders(st: RecoveryState) -> dict[str, TrackedOrder]:
    return {o.order_id: o for o in st.orders}


def _with_orders(st: RecoveryState, orders: dict[str, TrackedOrder]) -> RecoveryState:
    return replace(st, orders=tuple(orders[k] for k in sorted(orders)))


# ---------------------------------------------------------------------------------------------- apply


def apply(state: RecoveryState, item: StreamItem) -> Step:
    """Fold one item, in arrival order, into the state. A non-item raises ValueError (the caller records it with
    `note_problem`, since only the caller knows when it arrived)."""
    if not isinstance(state, RecoveryState):
        raise ValueError("state must be a RecoveryState")
    if isinstance(item, StreamMessage):
        return _message(state, item)
    if isinstance(item, SubscriptionOpened):
        return _opened(state, item)
    if isinstance(item, ConnectionLost):
        return _lost(state, item)
    if isinstance(item, BookObservation):
        return _book(state, item)
    raise ValueError(f"not a stream item: {type(item).__name__}")


def note_problem(state: RecoveryState, reason: Reason, *, at: datetime, detail: str,
                 market_ticker: str | None = None) -> RecoveryState:
    """A problem the caller saw (a backlog it could not drain, a failing source, a malformed item): it quarantines
    like any other, provable by a read that starts after `at`."""
    if not isinstance(reason, Reason):
        raise ValueError("reason must be a Reason")
    at_text = utc_text(at)
    return _quarantine(state, reason, market_ticker, at_text, at_text, detail)


def _message(st: RecoveryState, msg: StreamMessage) -> Step:
    cfg = st.config
    received, market = msg.clocks.received_at_utc, msg.market_ticker
    st, raised = _incoming(st, received)
    limit = parse_utc_text(received) + cfg.max_clock_skew
    for name, stamp in (("event", msg.clocks.event_at_utc), ("source", msg.clocks.source_at_utc),
                        ("send", msg.clocks.sent_at_utc)):
        if stamp is not None and parse_utc_text(stamp) > limit:
            st = _quarantine(st, Reason.CLOCK_SKEW, None, received, received,
                             f"the {name} stamp {stamp} is after our receipt {received}")
            raised.append(Reason.CLOCK_SKEW)
    sub = next((s for s in st.subscriptions if s.sid == msg.sid), None)
    if sub is None:
        if msg.sid in st.retired:
            st = _bump(st, market, f"a late message on retired subscription {msg.sid}", received)
            return _done(st, Applied.STALE_SUBSCRIPTION, raised, f"sid {msg.sid} is retired")
        st = _quarantine(st, Reason.UNKNOWN_SUBSCRIPTION, None, received, received, f"sid {msg.sid} was never opened")
        st = _bump(st, market, "a message on an unknown subscription", received)
        return _done(st, Applied.QUARANTINED, raised + [Reason.UNKNOWN_SUBSCRIPTION])
    if sub.channel is not msg.channel:
        st = _quarantine(st, Reason.CHANNEL_MISMATCH, None, received, received,
                         f"sid {msg.sid} is {sub.channel.value}, the message says {msg.channel.value}")
        st = _bump(st, market, "a message on the wrong channel", received)
        return _done(st, Applied.QUARANTINED, raised + [Reason.CHANNEL_MISMATCH])
    digest = msg.digest()
    if sub.last_seq is not None and msg.seq <= sub.last_seq:
        seen = next((d for s, q, d in st.recent if s == msg.sid and q == msg.seq), None)
        if seen == digest:
            return _done(st, Applied.DUPLICATE, raised, f"sid {msg.sid} seq {msg.seq} again")
        reason = Reason.OUT_OF_ORDER if seen is None else Reason.CONFLICTING_DUPLICATE
        detail = (f"sid {msg.sid} seq {msg.seq} after {sub.last_seq}, not matched" if seen is None
                  else f"sid {msg.sid} seq {msg.seq} carried two different messages")
        st = _quarantine(st, reason, None, received, received, detail)
        st = _bump(st, market, detail, received)
        return _done(st, Applied.QUARANTINED, raised + [reason], detail)
    expected = cfg.first_seq if sub.last_seq is None else sub.last_seq + 1
    if expected is not None and msg.seq != expected:
        st = _quarantine(st, Reason.SEQUENCE_GAP, None, received, received,
                         f"sid {msg.sid}: expected seq {expected}, got {msg.seq}")
        raised.append(Reason.SEQUENCE_GAP)
    updated = replace(sub, last_seq=msg.seq)
    for attr, name, stamp in (("last_source_utc", "source", msg.clocks.source_at_utc),
                              ("last_sent_utc", "send", msg.clocks.sent_at_utc)):
        previous = getattr(sub, attr)
        if stamp is None:
            continue
        if previous is not None and parse_utc_text(stamp) < parse_utc_text(previous):
            st = _quarantine(st, Reason.SOURCE_ORDER, None, received, received,
                             f"sid {msg.sid} seq {msg.seq}: the {name} stamp {stamp} is before {previous}")
            raised.append(Reason.SOURCE_ORDER)
            continue  # kept as it was: nothing is corrected backwards
        updated = replace(updated, **{attr: stamp})
    st = replace(st, subscriptions=tuple(updated if s.sid == sub.sid else s for s in st.subscriptions),
                 recent=(st.recent + ((msg.sid, msg.seq, digest),))[-cfg.dedupe_window:])
    return _event(st, msg, raised)


def _event(st: RecoveryState, msg: StreamMessage, raised: list[Reason]) -> Step:
    received, market, ev = msg.clocks.received_at_utc, msg.market_ticker, msg.event
    event_digest = msg.event_digest()
    if msg.corrects_event_id is not None:
        # A correction is a new observation linked to the one it corrects (append-only). The stream's
        # expectations on this market are dropped: only a REST read can say what stands now.
        st = _quarantine(st, Reason.CORRECTED_EVENT, market, received, received,
                         f"corrects {msg.corrects_event_id}")
        key = ev.fill_id if isinstance(ev, FillEvent) else f"order:{ev.order_id}"
        st = replace(st, events=(st.events + ((key, event_digest),))[-st.config.dedupe_window:])
        st = _with_orders(st, {k: o for k, o in _orders(st).items() if o.market_ticker != market})
        return _done(st, Applied.CORRECTION, raised + [Reason.CORRECTED_EVENT])
    orders = _orders(st)
    tracked = orders.get(ev.order_id)
    if tracked is not None and tracked.market_ticker != market:
        st = _quarantine(st, Reason.EVENT_CONFLICT, None, received, received,
                         f"order {ev.order_id} reported on {market} and {tracked.market_ticker}")
        st = _bump(st, market, f"order {ev.order_id} changed market", received)
        return _done(st, Applied.QUARANTINED, raised + [Reason.EVENT_CONFLICT])
    if isinstance(ev, FillEvent):
        prior = [d for k, d in st.events if k == ev.fill_id]
        if event_digest in prior:
            return _done(st, Applied.DUPLICATE_EVENT, raised, f"fill {ev.fill_id} again")
        st = replace(st, events=(st.events + ((ev.fill_id, event_digest),))[-st.config.dedupe_window:])
        if prior:
            st = _quarantine(st, Reason.EVENT_CONFLICT, market, received, received,
                             f"fill {ev.fill_id} delivered with different content and no correction")
            return _done(st, Applied.QUARANTINED, raised + [Reason.EVENT_CONFLICT])
        base = tracked or TrackedOrder(ev.order_id, market, None, None, None, (), received)
        if tracked is None and len(orders) >= st.config.max_tracked:
            st = _quarantine(st, Reason.TOO_MANY_TRACKED, None, received, received,
                             f"more than {st.config.max_tracked} orders")
            raised.append(Reason.TOO_MANY_TRACKED)
        else:
            orders[ev.order_id] = replace(base, fill_ids=base.fill_ids + (ev.fill_id,), last_received_utc=received)
            st = _with_orders(st, orders)
        st = _bump(st, market, f"fill {ev.fill_id} of order {ev.order_id}", received)
        return _done(st, Applied.APPLIED, raised)
    # an order update
    if tracked is not None and tracked.filled is not None and ev.fill_count < tracked.filled:
        st = _quarantine(st, Reason.REGRESSION, market, received, received,
                         f"order {ev.order_id} fill count {ev.fill_count} after {tracked.filled} (kept the higher)")
        return _done(st, Applied.QUARANTINED, raised + [Reason.REGRESSION])
    changed = tracked is None or (tracked.status, tracked.filled, tracked.remaining) != (
        ev.status, ev.fill_count, ev.remaining_count)
    if tracked is None and len(orders) >= st.config.max_tracked:
        st = _quarantine(st, Reason.TOO_MANY_TRACKED, None, received, received,
                         f"more than {st.config.max_tracked} orders")
        raised.append(Reason.TOO_MANY_TRACKED)
    else:
        base = tracked or TrackedOrder(ev.order_id, market, None, None, None, (), received)
        orders[ev.order_id] = replace(base, filled=ev.fill_count, status=ev.status, remaining=ev.remaining_count,
                                      last_received_utc=received)
        st = _with_orders(st, orders)
    if changed:
        st = _bump(st, market, f"order {ev.order_id} {ev.status} filled {ev.fill_count}", received)
    return _done(st, Applied.APPLIED, raised)


def _opened(st: RecoveryState, item: SubscriptionOpened) -> Step:
    cfg, at = st.config, item.at_utc
    st, raised = _incoming(st, at)
    if item.sid in st.retired or any(s.sid == item.sid for s in st.subscriptions):
        st = _quarantine(st, Reason.SID_REUSED, None, at, at, f"sid {item.sid} was already used")
        return _done(st, Applied.QUARANTINED, raised + [Reason.SID_REUSED])
    replaced = tuple(s.sid for s in st.subscriptions if s.channel is item.channel)
    st = replace(st, subscriptions=tuple(s for s in st.subscriptions if s.channel is not item.channel)
                 + (Subscription(item.sid, item.channel, at),),
                 retired=(st.retired + replaced)[-cfg.dedupe_window:])
    reason = Reason.RECONNECTED if replaced else Reason.BASELINE_REQUIRED
    st = _quarantine(st, reason, None, at, at, f"{item.channel.value} subscription {item.sid} opened"
                     + (f", replacing {list(replaced)}" if replaced else ""))
    raised.append(reason)
    opens = (st.opens + (at,))[-(cfg.max_opens_per_window + 1):]
    start = parse_utc_text(at) - cfg.reconnect_window
    n = sum(1 for t in opens if parse_utc_text(t) > start)
    st = replace(st, opens=opens)
    if n > cfg.max_opens_per_window:
        st = _quarantine(st, Reason.RECONNECT_STORM, None, at, _plus(at, cfg.reconnect_window),
                         f"{n} subscriptions opened within {cfg.reconnect_window.total_seconds()}s")
        raised.append(Reason.RECONNECT_STORM)
    return _done(st, Applied.OPENED, raised)


def _lost(st: RecoveryState, item: ConnectionLost) -> Step:
    """Every subscription ends. No order changes: a lost stream is not a cancelled order (STR-05)."""
    st, raised = _incoming(st, item.at_utc)
    gone = tuple(s.sid for s in st.subscriptions)
    st = replace(st, subscriptions=(), retired=(st.retired + gone)[-st.config.dedupe_window:])
    st = _quarantine(st, Reason.CONNECTION_LOST, None, item.at_utc, item.at_utc, item.reason)
    return _done(st, Applied.DISCONNECTED, raised + [Reason.CONNECTION_LOST], item.reason)


def _book(st: RecoveryState, item: BookObservation) -> Step:
    received, market = item.clocks.received_at_utc, item.market_ticker
    st, raised = _incoming(st, received)
    books = {b.market_ticker: b for b in st.books}
    prev = books.get(market)
    if prev is None and len(books) >= st.config.max_tracked:
        # Bounded: the least recently observed book is forgotten; its next observation is a fresh baseline.
        del books[min(books.values(), key=lambda b: (parse_utc_text(b.received_at_utc), b.market_ticker)).market_ticker]
    books[market] = Book(market, item.yes_bid, item.yes_ask, received)
    st = replace(st, books=tuple(books[k] for k in sorted(books)))
    if prev is not None:
        moves = []
        for side, old, new in (("bid", prev.yes_bid, item.yes_bid), ("ask", prev.yes_ask, item.yes_ask)):
            if (old is None) != (new is None):
                moves.append(f"{side} {old} -> {new}")
            elif old is not None and abs(new - old) > st.config.book_jump:
                moves.append(f"{side} {old} -> {new}")
        if moves:
            st = _bump(st, market, "book moved: " + ", ".join(moves), received)
            return _done(st, Applied.BOOK, raised, "; ".join(moves))
    return _done(st, Applied.BOOK, raised)


# ---------------------------------------------------------------------------------------------- proof


def prove(state: RecoveryState, reconciliation: acct.AccountReconciliation, *, scope: AccountScope) -> Proof:
    """Clear what a COMPLETE REST reconciliation of `scope` proves: every quarantine whose `not_before_utc` is at
    or before the read's start, except on markets where REST contradicts what the stream delivered before the read
    started (DISAGREEMENT, which stays quarantined until a later read agrees). Anything else proves nothing."""
    if not isinstance(state, RecoveryState):
        raise ValueError("state must be a RecoveryState")

    def refused(reason: str) -> Proof:
        return Proof(state, False, reason, None, (), ())

    if not isinstance(reconciliation, acct.AccountReconciliation):
        return refused("not an account reconciliation")
    if reconciliation.status is not acct.ReconciliationStatus.COMPLETE:
        return refused(f"the reconciliation is {reconciliation.status.value}: only COMPLETE proves")
    if reconciliation.manifest.plan.scope != scope:
        return refused("the reconciliation is of another account scope")
    rest_orders, rest_fills = {}, set()
    for sub in reconciliation.subaccounts:
        if sub.orders is None or sub.fills is None:
            return refused(f"subaccount {sub.subaccount}: orders or fills unknown")
        rest_orders.update({o.order_id: o for o in sub.orders})
        rest_fills |= {f.fill_id for f in sub.fills}
    started = reconciliation.manifest.started_at
    started_text, finished_text = utc_text(started), utc_text(reconciliation.manifest.finished_at)
    findings, kept, disagree = [], {}, {}
    for t in state.orders:
        if parse_utc_text(t.last_received_utc) > started:
            kept[t.order_id] = t  # newer than the read: it cannot be judged by it
            continue
        problems = []
        o = rest_orders.get(t.order_id)
        if o is None:
            problems.append(f"order {t.order_id} is not in the COMPLETE listing")
        elif t.filled is not None and t.filled > o.fill_count:
            problems.append(f"order {t.order_id}: the stream reported {t.filled} filled, REST {o.fill_count}")
        missing = sorted(f for f in t.fill_ids if f not in rest_fills)
        if missing:
            problems.append(f"order {t.order_id}: fills {missing[:5]} are not listed")
        if problems:
            detail = "; ".join(problems)[:300]
            findings.append(Finding(Reason.DISAGREEMENT.value, t.market_ticker, t.order_id, detail))
            disagree.setdefault(t.market_ticker, detail)
            kept[t.order_id] = t  # re-checked by the next proof
        elif o is not None and t.filled is not None and o.fill_count > t.filled:
            findings.append(Finding("REST_AHEAD_OF_STREAM", t.market_ticker, t.order_id,
                                    f"REST lists {o.fill_count} filled, the stream {t.filled} (REST wins)"))
    cleared = tuple(q for q in state.quarantines if parse_utc_text(q.not_before_utc) <= started)
    # Marks are pruned (bounded state): epochs come from a counter that never repeats, so a decision whose marks
    # were taken before this proof still sees its market as changed (conservative), never as unchanged.
    st = replace(state, quarantines=tuple(q for q in state.quarantines if q not in cleared),
                 orders=tuple(kept[k] for k in sorted(kept)), proven_at_utc=started_text, marks=())
    for market in sorted(disagree):
        st = _quarantine(st, Reason.DISAGREEMENT, market, finished_text, finished_text, disagree[market])
    cleared = tuple(q for q in cleared if not (q.reason is Reason.DISAGREEMENT and q.market_ticker in disagree))
    return Proof(st, True, None, started_text, cleared, tuple(findings))


# ---------------------------------------------------------------------------------------------- decisions


def epoch(state: RecoveryState, market_ticker: str) -> int:
    return next((m.epoch for m in state.marks if m.market_ticker == market_ticker), 0)


def marks(state: RecoveryState) -> Marks:
    return Marks(state.account_epoch, MappingProxyType({m.market_ticker: m.epoch for m in state.marks}))


def decision_problems(state: RecoveryState, market_ticker: str, since: Marks) -> tuple[str, ...]:
    """Why a decision on `market_ticker` taken at `since` may not proceed now (empty: it may)."""
    out = []
    missing = state.config.required_channels - state.channels
    if missing:
        out.append(f"STREAM_DOWN: no live subscription for {sorted(c.value for c in missing)}")
    for q in state.quarantines:
        if q.market_ticker is None or q.market_ticker == market_ticker:
            scope = "account" if q.market_ticker is None else q.market_ticker
            out.append(f"STREAM_QUARANTINE: {q.reason.value} ({scope}) since {q.since_utc}: {q.detail}"[:300])
    if state.account_epoch != since.account_epoch:
        out.append(f"STREAM_INVALIDATED: account-wide change ({state.account_reason})"[:300])
    if epoch(state, market_ticker) != since.epochs.get(market_ticker, 0):
        mark = next((m for m in state.marks if m.market_ticker == market_ticker), None)
        why = "its marks were pruned by a later proof" if mark is None else f"changed at {mark.at_utc} ({mark.reason})"
        out.append(f"STREAM_INVALIDATED: {market_ticker} {why}"[:300])
    return tuple(out)


def summary(state: RecoveryState) -> dict:
    """A small, JSON-ready description of the state (for a cycle record)."""
    return {"incoming": state.incoming, "connected": state.connected,
            "subscriptions": [[s.sid, s.channel.value, s.last_seq] for s in state.subscriptions],
            "quarantines": [[q.reason.value, q.market_ticker, q.since_utc] for q in state.quarantines],
            "counts": dict(state.counts), "proven_at_utc": state.proven_at_utc}
