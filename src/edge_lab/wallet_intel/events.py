"""Normalized wallet observations, conservative action taxonomy and an append-only log (W2, ADR 0045).

**One observation is one action on one account**, as one source reported it. It keeps every field
of directive §8: source/product/chain, account, source event id, transaction id, the
log/instruction/fill index where the source gives one, action, native instrument, native quantity
and decimals, paid and received assets, price basis, fees, source and receipt time, finality, the
raw evidence reference, the parser version, confidence/coverage notes and corrections.

**Identity and deduplication use event semantics, never the transaction hash alone.**
- One transaction can carry several fills. Each stays its own observation.
- With a source event id (a fill id, a trade id) that id is the identity.
- Without one (Polymarket Data API v2 rows carry only `transaction_hash`), the identity is a hash of
  the row's semantic content plus an *occurrence* number. Two identical rows in one retrieval are two
  observations (`INDISTINGUISHABLE_DUPLICATE_ROWS` is recorded), never one.
- Re-receiving the same identity is a duplicate. The earliest receipt time is kept, because a
  point-in-time decision may only use what had arrived by then.
- The same source event id or occurrence identity with different content is a **conflict**. Both
  versions are kept and the conflict is reported; nothing silently wins. So is one transaction
  reported with two block times.

**Taxonomy.** Only TRADE_BUY and TRADE_SELL are directional. Transfers, splits, merges, redemptions,
rewards and conversions are not buys or sells, and an UNKNOWN action is never followed.

**Corrections are appended** (`Correction`): a retraction, a supersession or a finality change
(a reorg). `as_known_at(t)` replays the log as it stood at knowledge time `t`. History is never
rewritten, and a retracted leader event never undoes anything a follower did (W6 keeps its own
records).

**Position effects** (`classify_effects`) are judged against the reconstructed position. Without a
complete history from the account's start, or with legs a source does not itemize, the effect is
UNKNOWN, never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Iterable, Sequence

from ..provenance import canonical_json, sha256_hex
from .exact import ZERO, Labeled, add, decimal_text, exact_decimal, sub
from .identity import AccountRef
from .timeutil import require_aware, utc_text

EVENT_SCHEMA = "wallet-observation-v1"


class Action(str, Enum):
    TRADE_BUY = "TRADE_BUY"
    TRADE_SELL = "TRADE_SELL"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    SPLIT = "SPLIT"
    MERGE = "MERGE"
    REDEEM = "REDEEM"
    REWARD = "REWARD"
    CONVERSION = "CONVERSION"
    UNKNOWN = "UNKNOWN"


DIRECTIONAL = frozenset({Action.TRADE_BUY, Action.TRADE_SELL})


def is_directional(action: Action) -> bool:
    """Only trades express a direction. Everything else, UNKNOWN included, is not followable."""
    return action in DIRECTIONAL


class ChainFinality(str, Enum):
    UNCONFIRMED = "UNCONFIRMED"  # seen (mempool, preprocessed, processed) but may never land
    CONFIRMED = "CONFIRMED"  # included, still reorganizable
    FINAL = "FINAL"
    REORGED_OUT = "REORGED_OUT"  # set only by a correction
    UNKNOWN = "UNKNOWN"  # the source does not document finality


class IdentityBasis(str, Enum):
    SOURCE_EVENT_ID = "SOURCE_EVENT_ID"
    SEMANTIC_WITH_OCCURRENCE = "SEMANTIC_WITH_OCCURRENCE"


CASH_ASSETS = frozenset({"USDC", "PUSD", "USD"})
_NEVER = datetime.max.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class AssetAmount:
    """`quantity` (> 0) of `asset`. Cash assets use their symbol; outcome tokens use `token:<id>`."""

    asset: str
    quantity: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", exact_decimal(self.quantity, name=f"{self.asset} quantity"))
        if not self.asset or self.quantity <= 0:
            raise ValueError("an asset leg needs an asset and a positive quantity")

    @property
    def is_cash(self) -> bool:
        return self.asset.upper() in CASH_ASSETS


def token_asset(token_id: str) -> str:
    return f"token:{token_id}"


@dataclass(frozen=True)
class WalletObservation:
    source: str
    product: str
    chain: str | None
    account: AccountRef
    source_event_id: str | None
    transaction_id: str | None
    sub_index: int | None  # log / instruction / fill index, where the source gives one
    occurrence: int  # among semantically identical rows of one retrieval (0 when ids exist)
    action: Action
    raw_action: str
    instrument_id: str | None  # native token id
    market_id: str | None  # e.g. a condition id
    event_id: str | None  # the real-world event (dependence cluster)
    outcome_index: int | None
    native_quantity: Decimal | None
    native_decimals: int | None  # None: the source reports scaled values and does not state decimals
    paid: tuple[AssetAmount, ...]
    received: tuple[AssetAmount, ...]
    price: Decimal | None
    price_basis: str | None
    fee: Labeled
    source_time: datetime
    receipt_time: datetime
    finality: ChainFinality
    raw_ref: str
    parser_version: str
    category: str | None = None
    ambiguities: tuple[str, ...] = ()
    synthetic: bool = False

    def __post_init__(self) -> None:
        require_aware(self.source_time, "source_time")
        require_aware(self.receipt_time, "receipt_time")
        if not isinstance(self.action, Action):
            raise ValueError("action must be an Action")
        if self.occurrence < 0:
            raise ValueError("occurrence must be >= 0")
        for name in ("native_quantity", "price"):
            v = getattr(self, name)
            if v is not None:
                object.__setattr__(self, name, exact_decimal(v, name=name))
        if not isinstance(self.fee, Labeled):
            raise ValueError("fee must be Labeled (UNKNOWN when the source does not report it)")
        if not self.raw_ref or not self.parser_version:
            raise ValueError("an observation needs a raw evidence reference and a parser version")
        if self.action in DIRECTIONAL and (self.instrument_id is None or self.native_quantity is None):
            raise ValueError("a trade needs an instrument and a quantity")

    # Identity -------------------------------------------------------------------------------------
    def semantic_content(self) -> dict:
        """What the event *is*: excludes receipt time, raw reference, parser version and occurrence."""
        return {
            "schema": EVENT_SCHEMA, "source": self.source, "product": self.product, "chain": self.chain,
            "account": self.account.key, "source_event_id": self.source_event_id,
            "transaction_id": None if self.transaction_id is None else self.transaction_id.lower(),
            "sub_index": self.sub_index, "action": self.action.value, "raw_action": self.raw_action,
            "instrument_id": self.instrument_id, "market_id": self.market_id,
            "outcome_index": self.outcome_index,
            "native_quantity": _txt(self.native_quantity), "price": _txt(self.price),
            "paid": [[a.asset, decimal_text(a.quantity)] for a in self.paid],
            "received": [[a.asset, decimal_text(a.quantity)] for a in self.received],
            "fee": self.fee.to_dict(), "source_time": utc_text(self.source_time),
        }

    @property
    def semantic_key(self) -> str:
        return sha256_hex(canonical_json(self.semantic_content()))

    @property
    def identity_basis(self) -> IdentityBasis:
        return IdentityBasis.SOURCE_EVENT_ID if self.source_event_id else IdentityBasis.SEMANTIC_WITH_OCCURRENCE

    @property
    def observation_id(self) -> str:
        if self.source_event_id:
            return f"{self.source}:{self.account.key}:evt:{self.source_event_id}"
        if self.sub_index is not None and self.transaction_id:
            return f"{self.source}:{self.account.key}:tx:{self.transaction_id.lower()}:{self.sub_index}"
        return f"{self.source}:sem:{self.semantic_key[:32]}:{self.occurrence}"

    @property
    def directional(self) -> bool:
        return is_directional(self.action)


def _txt(v: Decimal | None) -> str | None:
    return None if v is None else decimal_text(v)


def assign_occurrences(observations: Sequence[WalletObservation]) -> tuple[WalletObservation, ...]:
    """Number semantically identical rows of ONE retrieval 0, 1, 2... so several identical fills in a
    transaction stay distinct. Rows with a source event id or a sub-index keep occurrence 0."""
    counts: dict[str, int] = {}
    out = []
    for obs in observations:
        if obs.source_event_id or obs.sub_index is not None:
            out.append(obs)
            continue
        key = obs.semantic_key
        n = counts.get(key, 0)
        counts[key] = n + 1
        if n:
            out.append(replace(obs, occurrence=n,
                               ambiguities=tuple(sorted({*obs.ambiguities, "INDISTINGUISHABLE_DUPLICATE_ROWS"}))))
        else:
            out.append(obs)
    # The first of a duplicated group is ambiguous too.
    dup_keys = {k for k, c in counts.items() if c > 1}
    return tuple(replace(o, ambiguities=tuple(sorted({*o.ambiguities, "INDISTINGUISHABLE_DUPLICATE_ROWS"})))
                 if (not o.source_event_id and o.sub_index is None and o.occurrence == 0
                     and o.semantic_key in dup_keys) else o for o in out)


class CorrectionKind(str, Enum):
    RETRACTED = "RETRACTED"
    SUPERSEDED = "SUPERSEDED"
    FINALITY_CHANGED = "FINALITY_CHANGED"


@dataclass(frozen=True)
class Correction:
    correction_id: str
    target_id: str
    kind: CorrectionKind
    recorded_at: datetime  # knowledge time
    reason: str
    replacement: WalletObservation | None = None
    new_finality: ChainFinality | None = None

    def __post_init__(self) -> None:
        require_aware(self.recorded_at, "recorded_at")
        if self.kind is CorrectionKind.SUPERSEDED and self.replacement is None:
            raise ValueError("a supersession needs its replacement")
        if self.kind is CorrectionKind.FINALITY_CHANGED and self.new_finality is None:
            raise ValueError("a finality change needs the new finality")
        if not self.reason:
            raise ValueError("a correction needs a reason")


@dataclass(frozen=True)
class Conflict:
    kind: str  # SAME_IDENTITY_DIFFERENT_CONTENT | TRANSACTION_TIME_MISMATCH
    key: str
    first: str  # semantic keys of the two versions
    second: str
    detected_at: datetime


@dataclass
class _Entry:
    obs: WalletObservation
    first_receipt: datetime
    receipts: int = 1


@dataclass
class ObservationLog:
    """Append-only. Entries, corrections and conflicts are only ever added."""

    _entries: dict[str, _Entry] = field(default_factory=dict)
    _order: list[str] = field(default_factory=list)
    _corrections: list[Correction] = field(default_factory=list)
    _conflicts: list[Conflict] = field(default_factory=list)
    _variants: dict[str, list[WalletObservation]] = field(default_factory=dict)
    _tx_times: dict[str, datetime] = field(default_factory=dict)
    _conflicted_tx: dict[str, datetime] = field(default_factory=dict)  # tx key -> earliest detection
    _conflicted_ids: dict[str, datetime] = field(default_factory=dict)  # identity -> earliest detection

    def ingest(self, observations: Iterable[WalletObservation]) -> dict[str, int]:
        """Add one retrieval's observations (occurrences already assigned). Returns counts."""
        added = dup = conflicts = 0
        for obs in observations:
            oid = obs.observation_id
            tx = obs.transaction_id.lower() if obs.transaction_id else None
            if tx is not None:
                key = f"{obs.source}|{tx}"
                seen = self._tx_times.get(key)
                if seen is None:
                    self._tx_times[key] = obs.source_time
                elif seen != obs.source_time:
                    if key not in self._conflicted_tx or obs.receipt_time < self._conflicted_tx[key]:
                        self._conflicted_tx[key] = obs.receipt_time
                    self._conflicts.append(Conflict("TRANSACTION_TIME_MISMATCH", key, utc_text(seen),
                                                    utc_text(obs.source_time), obs.receipt_time))
                    conflicts += 1
            entry = self._entries.get(oid)
            if entry is None:
                self._entries[oid] = _Entry(obs, obs.receipt_time)
                self._order.append(oid)
                added += 1
                continue
            if entry.obs.semantic_key == obs.semantic_key:
                entry.receipts += 1
                if obs.receipt_time < entry.first_receipt:
                    entry.first_receipt = obs.receipt_time
                dup += 1
                continue
            variants = self._variants.setdefault(oid, [])
            if all(v.semantic_key != obs.semantic_key for v in variants):
                variants.append(obs)
                if oid not in self._conflicted_ids or obs.receipt_time < self._conflicted_ids[oid]:
                    self._conflicted_ids[oid] = obs.receipt_time
                self._conflicts.append(Conflict("SAME_IDENTITY_DIFFERENT_CONTENT", oid, entry.obs.semantic_key,
                                                obs.semantic_key, obs.receipt_time))
                conflicts += 1
        return {"added": added, "duplicates": dup, "conflicts": conflicts}

    def append_correction(self, correction: Correction) -> None:
        if correction.target_id not in self._entries:
            raise ValueError(f"unknown observation {correction.target_id}")
        if any(c.correction_id == correction.correction_id for c in self._corrections):
            raise ValueError(f"correction {correction.correction_id} already recorded")
        self._corrections.append(correction)

    @property
    def conflicts(self) -> tuple[Conflict, ...]:
        return tuple(self._conflicts)

    @property
    def corrections(self) -> tuple[Correction, ...]:
        return tuple(self._corrections)

    def conflicted_ids(self, known_at: datetime | None = None) -> frozenset[str]:
        """Identities with two contents, plus every observation of a transaction with two block times.

        With `known_at`, only conflicts detected by then count: a version that arrives later never
        changes what an earlier point-in-time view contained."""

        def by(when: datetime) -> bool:
            return known_at is None or when <= known_at

        tx_hit = {oid for oid, e in self._entries.items() if e.obs.transaction_id
                  and by(self._conflicted_tx.get(f"{e.obs.source}|{e.obs.transaction_id.lower()}", _NEVER))}
        return frozenset(oid for oid, when in self._conflicted_ids.items() if by(when)) | frozenset(tx_hit)

    def first_receipt(self, observation_id: str) -> datetime:
        return self._entries[observation_id].first_receipt

    def all_ids(self) -> tuple[str, ...]:
        return tuple(self._order)

    def version_at(self, observation_id: str, known_at: datetime, *, include_conflicted: bool = False,
                   _conflicted: frozenset[str] | None = None) -> WalletObservation | None:
        """One identity as it stood at knowledge time `known_at` (None: not yet received, retracted,
        reorged out, or conflicted by then)."""
        require_aware(known_at, "known_at")
        entry = self._entries.get(observation_id)
        if entry is None or entry.first_receipt > known_at:
            return None
        conflicted = self.conflicted_ids(known_at) if _conflicted is None else _conflicted
        if not include_conflicted and observation_id in conflicted:
            return None
        obs: WalletObservation | None = entry.obs
        for c in self._corrections:
            if c.target_id != observation_id or c.recorded_at > known_at or obs is None:
                continue
            if c.kind is CorrectionKind.RETRACTED:
                obs = None
            elif c.kind is CorrectionKind.SUPERSEDED:
                obs = c.replacement
            elif c.kind is CorrectionKind.FINALITY_CHANGED:
                obs = None if c.new_finality is ChainFinality.REORGED_OUT else replace(obs, finality=c.new_finality)
        return obs

    def as_known_at(self, known_at: datetime, *, include_conflicted: bool = False) -> tuple[WalletObservation, ...]:
        """The log as it stood at knowledge time `known_at`, with corrections recorded by then.

        An observation counts only once its first receipt is at or before `known_at`. Conflicted
        identities are left out unless asked for (they are reported, not resolved)."""
        require_aware(known_at, "known_at")
        conflicted = self.conflicted_ids(known_at)
        out = [o for o in (self.version_at(oid, known_at, include_conflicted=include_conflicted,
                                           _conflicted=conflicted) for oid in self._order) if o is not None]
        return tuple(sorted(out, key=lambda o: (o.source_time, o.observation_id)))


# --- Position effects ------------------------------------------------------------------------------

class PositionEffect(str, Enum):
    OPEN = "OPEN"
    INCREASE = "INCREASE"
    REDUCE = "REDUCE"
    CLOSE = "CLOSE"
    FLIP = "FLIP"
    NOT_DIRECTIONAL = "NOT_DIRECTIONAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class EffectRow:
    observation_id: str
    effect: PositionEffect
    reason: str


def classify_effects(observations: Sequence[WalletObservation], *, history_complete: bool) -> tuple[EffectRow, ...]:
    """Classify each trade against the account's reconstructed binary-market position.

    Net exposure in a market is (holding of outcome 0) - (holding of outcome 1). OPEN starts from
    zero, INCREASE/REDUCE keep the sign, CLOSE returns to zero and FLIP crosses zero. UNKNOWN when the
    history is not complete from the account's start, a leg is not itemized, an outcome index is
    missing or not binary, or a sale exceeds the reconstructed holding (missing history).
    """
    rows: list[EffectRow] = []
    holdings: dict[tuple[str, str], dict[int, Decimal]] = {}
    unknown_markets: set[tuple[str, str]] = set()
    token_outcome: dict[str, int] = {}
    for o in observations:
        if o.instrument_id is not None and o.outcome_index is not None:
            token_outcome[o.instrument_id] = o.outcome_index
    for o in sorted(observations, key=lambda x: (x.source_time, x.observation_id)):
        mkey = (o.account.key, o.market_id or "")
        if not history_complete:
            rows.append(EffectRow(o.observation_id, PositionEffect.NOT_DIRECTIONAL if not o.directional
                                  else PositionEffect.UNKNOWN, "history is not complete from the account's start"))
            continue
        if o.market_id is None:
            rows.append(EffectRow(o.observation_id, PositionEffect.UNKNOWN if o.directional
                                  else PositionEffect.NOT_DIRECTIONAL, "no market id"))
            continue
        book = holdings.setdefault(mkey, {})
        before = _net(book)
        problem = _apply_legs(o, book, token_outcome)
        if problem:
            unknown_markets.add(mkey)
        if not o.directional:
            rows.append(EffectRow(o.observation_id, PositionEffect.NOT_DIRECTIONAL, o.action.value))
            continue
        if mkey in unknown_markets or before is None:
            rows.append(EffectRow(o.observation_id, PositionEffect.UNKNOWN, problem or "position is unknown"))
            continue
        after = _net(book)
        if after is None:
            rows.append(EffectRow(o.observation_id, PositionEffect.UNKNOWN, "position is unknown"))
            continue
        rows.append(EffectRow(o.observation_id, _effect(before, after), f"net {decimal_text(before)} -> "
                                                                        f"{decimal_text(after)}"))
    return tuple(rows)


def _net(book: dict[int, Decimal]) -> Decimal | None:
    if any(k not in (0, 1) for k in book):
        return None
    return sub(book.get(0, ZERO), book.get(1, ZERO))


def _apply_legs(o: WalletObservation, book: dict[int, Decimal], token_outcome: dict[str, int]) -> str | None:
    if "LEGS_NOT_ITEMIZED" in o.ambiguities:
        return "the source does not itemize this action's token legs"
    for leg, sign in [*((a, 1) for a in o.received), *((a, -1) for a in o.paid)]:
        if leg.is_cash:
            continue
        token = leg.asset.removeprefix("token:")
        idx = token_outcome.get(token)
        if idx is None or idx not in (0, 1):
            return f"outcome of {leg.asset} is unknown or not binary"
        new = add(book.get(idx, ZERO), leg.quantity) if sign > 0 else sub(book.get(idx, ZERO), leg.quantity)
        if new < 0:
            return f"a sale of {leg.asset} exceeds the reconstructed holding (missing history)"
        book[idx] = new
    return None


def _effect(before: Decimal, after: Decimal) -> PositionEffect:
    if before == 0:
        return PositionEffect.OPEN if after != 0 else PositionEffect.UNKNOWN
    if after == 0:
        return PositionEffect.CLOSE
    if (before > 0) != (after > 0):
        return PositionEffect.FLIP
    return PositionEffect.INCREASE if abs(after) > abs(before) else PositionEffect.REDUCE
