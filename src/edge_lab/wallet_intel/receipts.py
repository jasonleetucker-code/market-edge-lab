"""v2 causal wallet-selection receipts (Deliverable A of #181/#168; ADR 0045 Amendment 2026-10-08 A).

The v1 manifest's `inputs_digest` binds the cutoff, the label version, the rule id and version, candidates,
observation ids and marks. It does not bind the rule's thresholds, coverage, threat flags, the mark-age
tolerance, the discovery source, the trial history, observation contents or correction state
(`selection.LEGACY_V1_UNBOUND`). Two different selections could therefore share one v1 digest. That is
**incomplete causal input binding**, not a hash collision.

A v2 receipt binds the **complete deterministic dependency closure** of one point-in-time selection:
- `rule` + `rule_units`: every effective `EligibilityRule` field, with canonical Decimal text for money and
  shares, exact binary64 text for the float threshold, microsecond durations and declared units;
- `engine`: the engine and code versions plus every implicit parameter (prior fit, shrinkage level,
  lookback, inactivity and mark-selection rules), read from the loaded code, never assumed;
- `candidates`: every discovery of each account known by the cutoff (first discovery, source and label
  vintage), its identity snapshot as known by the cutoff (UNKNOWN when no registry was supplied), the
  coverage assertion and the threat/quality assertions in force at the cutoff with their provenance and
  knowledge times, and its observation history as known by the cutoff: each identity's first receipt and
  status, corrections in their per-target order, conflicts detected by then, and the full content and
  hash of every effective observation;
- `marks`: the mark in force per instrument at the cutoff, with its quote basis, as-of and receipt
  times, source and evidence reference; `mark_freshness` holds the tolerance;
- `trials`: the cumulative trial count, its source and the digests of earlier receipts it counts.

Downstream reports (price-relative skill, follower replay) bind to a receipt through typed
`DownstreamSlot`s. Their closures are hashed into the receipt digest, never into the selection's own
closure digest, so the dependency stays one-way.

Everything is explicit: `build_receipt(inputs)` reads only its argument and the loaded code. `rebuild`
re-derives a receipt from a persisted record alone, and `verify` reports VERIFIED or exactly one
deterministic failure. A v1 record verifies as LEGACY_INCOMPLETE and `load_receipt` refuses it: a v1
record is never upgraded or described as fully replayable.

Unknown stays unknown: a coverage assertion of `None` is COVERAGE_UNKNOWN, and a flag assertion of
`None` is an unassessed screen. Both make a candidate ineligible; neither is coerced to a clean answer.
A missing input (no log, no coverage or threat assertion in force at the cutoff) fails closed.
"""

from __future__ import annotations

import inspect
import json
import math
import re
from dataclasses import dataclass, fields, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Mapping, Sequence

from .. import provenance
from ..provenance import canonical_json, sha256_hex
from . import WALLET_INTEL_VERSION, accounting, events, exact, identity, market_data, selection, stats, threats, \
    timeutil
from .accounting import ACCOUNTING_VERSION, Mark, MarkKind
from .events import EVENT_SCHEMA, Action, AssetAmount, ChainFinality, Correction, CorrectionKind, ObservationLog, \
    WalletObservation
from .exact import Basis, Labeled, decimal_text, exact_decimal
from .identity import AccountRef, IdentityBasis, IdentityRegistry, MappingRevocation, ProxyMapping, RelationKind
from .selection import (LEGACY_V1_STATUS, LEGACY_V1_UNBOUND, PRIOR_MIN_CANDIDATES, SELECTION_VERSION, Candidate,
                        CandidateStatus, EligibilityRule, HindsightError, SelectionRecord, decide, multiple_testing)
from .stats import WEAK_PRIOR, BetaPrior, shrunk_rate
from .timeutil import require_aware, utc_text

RECEIPT_SCHEMA = "wallet-selection-receipt-v2"
CLOSURE_SCHEMA = "wallet-selection-closure-v2"
ENGINE_VERSION = "wallet-selection-engine-v2"
REPLAYABILITY_V2 = "FULL_CLOSURE_V2"
_HEX64 = re.compile(r"[0-9a-f]{64}")
_CODE = re.compile(r"[A-Z0-9][A-Z0-9_:.\-]{0,127}")


# --- Errors ----------------------------------------------------------------------------------------

class ReceiptInputError(ValueError):
    """A v2 receipt cannot be built or read: an input is missing, ambiguous or malformed."""


class MissingInputError(ReceiptInputError):
    """A causal input the closure needs is absent at the cutoff (fail closed)."""


class AmbiguousInputError(ReceiptInputError):
    """Two different inputs claim the same slot at the same knowledge time (fail closed)."""


class MalformedReceiptError(ReceiptInputError):
    """A persisted receipt does not decode, or does not re-encode to itself."""


class BackfillOrderError(ReceiptInputError):
    """The log was filled out of knowledge order in a way that would let information from after the
    cutoff, or an order other than knowledge order, shape the view (fail closed)."""


class EngineMismatchError(ReceiptInputError):
    """The record was built by an engine (versions, parameters or source) other than the loaded one."""


class CausalityError(HindsightError):
    """A closure claims knowledge from after its own cutoff."""


class DownstreamBindingError(ValueError):
    """A downstream binding does not match its slot, receipt or digest."""


class LegacyReceiptError(ValueError):
    """A v1 record was offered where a v2 receipt is required. It is never upgraded."""


# --- Typed inputs -----------------------------------------------------------------------------------

def _text_field(value: object, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be non-empty text")


@dataclass(frozen=True)
class CoverageAssertion:
    """Whether an account's observation history is complete from its start, as asserted by `source`
    at knowledge time `known_at`. `history_complete=None` is UNKNOWN, never False or True."""

    account_key: str
    history_complete: bool | None
    source: str
    method_version: str
    known_at: datetime
    evidence_ref: str

    def __post_init__(self) -> None:
        for name in ("account_key", "source", "method_version", "evidence_ref"):
            _text_field(getattr(self, name), name)
        if self.history_complete is not None and not isinstance(self.history_complete, bool):
            raise ValueError("history_complete must be True, False or None (UNKNOWN)")
        require_aware(self.known_at, "known_at")


class FlagKind(str, Enum):
    THREAT = "THREAT"  # threats.py-style screens; at least one assertion per candidate is required
    QUALITY = "QUALITY"  # data-quality screens; optional


@dataclass(frozen=True)
class FlagAssertion:
    """Flag codes one screen (`source` at `method_version`) asserted for an account at `known_at`.
    `flags=()` means assessed with nothing flagged; `flags=None` means not assessed (UNKNOWN)."""

    account_key: str
    kind: FlagKind
    flags: tuple[str, ...] | None
    source: str
    method_version: str
    known_at: datetime
    evidence_ref: str

    def __post_init__(self) -> None:
        for name in ("account_key", "source", "method_version", "evidence_ref"):
            _text_field(getattr(self, name), name)
        if not isinstance(self.kind, FlagKind):
            raise ValueError("kind must be a FlagKind")
        if self.flags is not None:
            if not isinstance(self.flags, (list, tuple)):
                raise TypeError("flags must be a sequence of flag codes, or None when not assessed")
            for code in self.flags:
                if not isinstance(code, str) or not _CODE.fullmatch(code):
                    raise TypeError(f"flag {code!r} is not a flag code")
            object.__setattr__(self, "flags", tuple(self.flags))
        require_aware(self.known_at, "known_at")


@dataclass(frozen=True)
class MarkEvidence:
    """A mark with the evidence behind it: its quote basis (e.g. BOOK_BEST_BID_WITH_DEPTH,
    SETTLEMENT_PAYOUT), source, receipt time and raw evidence reference. `received_at` is the
    knowledge time; a mark cannot be received before its own as-of time."""

    mark: Mark
    source: str
    received_at: datetime
    quote_basis: str
    evidence_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.mark, Mark):
            raise ValueError("mark must be a Mark")
        for name in ("source", "quote_basis", "evidence_ref"):
            _text_field(getattr(self, name), name)
        require_aware(self.received_at, "received_at")
        if self.received_at < self.mark.as_of:
            raise ValueError("a mark cannot be received before its as-of time")


@dataclass(frozen=True)
class TrialBasis:
    """The cumulative number of selection-rule trials (this one included), where that count comes from,
    and the digests of the earlier v2 receipts it counts. Earlier trials without a v2 receipt (legacy
    runs) are counted but cannot be listed."""

    count: int
    source: str
    prior_receipt_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 1:
            raise ValueError("trials.count must be an integer >= 1")
        _text_field(self.source, "source")
        if not isinstance(self.prior_receipt_digests, (list, tuple)):
            raise TypeError("prior_receipt_digests must be a sequence of digests")
        for d in self.prior_receipt_digests:
            if not isinstance(d, str) or not _HEX64.fullmatch(d):
                raise ValueError(f"not a sha256 hex digest: {d!r}")
        object.__setattr__(self, "prior_receipt_digests", tuple(self.prior_receipt_digests))
        if self.count < len(set(self.prior_receipt_digests)) + 1:
            raise ValueError("trials.count must count every listed earlier receipt plus this one")


@dataclass(frozen=True)
class SelectionInputsV2:
    """Everything one v2 selection may depend on. Inputs from after `cutoff` may be passed (a whole
    log, a revised assertion, a later mark); they are filtered by knowledge time and never reach the
    closure. A candidate visible at the cutoff needs a log (empty is fine), a coverage assertion and
    at least one THREAT assertion in force at the cutoff."""

    cutoff: datetime
    label_version: str
    rule: EligibilityRule
    mark_max_age: timedelta
    candidates: Sequence[Candidate]
    logs: Mapping[str, ObservationLog]
    coverage: Sequence[CoverageAssertion]
    flags: Sequence[FlagAssertion]
    marks: Sequence[MarkEvidence]
    trials: TrialBasis
    identity: IdentityRegistry | None = None  # None: the identity snapshot is UNKNOWN
    fdr_q: float = 0.10  # Benjamini-Hochberg q for the receipted multiple-testing screen (bound)


# --- Downstream extension point ----------------------------------------------------------------------

class DownstreamSlot(str, Enum):
    PRICE_RELATIVE_SKILL = "PRICE_RELATIVE_SKILL"  # Deliverable C binds its dependency closure here
    FOLLOWER_REPLAY = "FOLLOWER_REPLAY"  # Deliverable D binds its dependency closure here


# The key in each slot's downstream closure that names the selection it was computed on. Binding checks
# it equals this receipt's closure digest (lane C: `SkillClosure.cohort_ref`).
SLOT_SELECTION_REF: dict[DownstreamSlot, str] = {
    DownstreamSlot.PRICE_RELATIVE_SKILL: "cohort_ref",
    DownstreamSlot.FOLLOWER_REPLAY: "selection_ref",
}

NOT_BOUND = {"status": "NOT_BOUND"}


def _plain_json(value: object, where: str) -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DownstreamBindingError(f"{where}: non-finite float")
        return
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _plain_json(v, f"{where}[{i}]")
        return
    if isinstance(value, Mapping):
        for k, v in value.items():
            if not isinstance(k, str):
                raise DownstreamBindingError(f"{where}: keys must be text")
            _plain_json(v, f"{where}.{k}")
        return
    raise DownstreamBindingError(f"{where}: {type(value).__name__} is not plain JSON (canonicalize it first)")


@dataclass(frozen=True)
class DownstreamBinding:
    """A downstream report's dependency closure, bound to one selection closure digest. The closure is
    plain JSON (Decimals and times already canonical text) and is hashed with the same scheme, so its
    digest equals the report's own closure digest (e.g. `SkillClosure.digest`). The closure must name
    the same selection under its slot's `SLOT_SELECTION_REF` key. `report_digest` optionally binds the
    downstream report itself (None: not bound)."""

    slot: DownstreamSlot
    schema: str
    selection_digest: str
    closure: Mapping[str, Any]
    report_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.slot, DownstreamSlot):
            raise DownstreamBindingError("slot must be a DownstreamSlot")
        if not isinstance(self.schema, str) or not self.schema:
            raise DownstreamBindingError("a downstream binding needs its schema/version id")
        if not isinstance(self.selection_digest, str) or not _HEX64.fullmatch(self.selection_digest):
            raise DownstreamBindingError("selection_digest must be a sha256 hex digest")
        if self.report_digest is not None and (not isinstance(self.report_digest, str)
                                               or not _HEX64.fullmatch(self.report_digest)):
            raise DownstreamBindingError("report_digest must be a sha256 hex digest or None")
        if not isinstance(self.closure, Mapping) or not self.closure:
            raise DownstreamBindingError("a downstream closure must be a non-empty mapping")
        _plain_json(self.closure, "closure")
        ref_key = SLOT_SELECTION_REF[self.slot]
        if self.closure.get(ref_key) != self.selection_digest:
            raise DownstreamBindingError(f"{self.slot.value}: closure[{ref_key!r}] must name this selection digest")
        object.__setattr__(self, "closure", json.loads(canonical_json(self.closure)))

    @property
    def closure_digest(self) -> str:
        return sha256_hex(canonical_json(self.closure))

    def to_dict(self) -> dict:
        return {"status": "BOUND", "schema": self.schema, "selection_digest": self.selection_digest,
                "closure": json.loads(canonical_json(self.closure)), "closure_digest": self.closure_digest,
                "report_digest": self.report_digest}


# --- Canonical codec ---------------------------------------------------------------------------------
# One field-spec table per bound type. Encoding refuses a dataclass field the table does not name, so
# a new field cannot silently escape the digest; decoding refuses missing or extra keys.

_SPECS: dict[str, tuple[type, dict[str, object]]] = {
    "EligibilityRule": (EligibilityRule, {
        "rule_id": "text", "version": "text", "min_independent_events": "count", "min_history_days": "count",
        "min_shrunk_lower": "binary64", "max_concentration": "decimal", "max_round_trip_share": "decimal",
        "max_reward_dependence": "decimal", "inactive_after": "duration", "round_trip_window": "duration",
        "min_trade_notional": "decimal", "require_complete_coverage": "bool"}),
    "Candidate": (Candidate, {"account": ("obj", "AccountRef"), "discovered_at": "time", "discovery_source": "text",
                              "discovery_label_version": "text"}),
    "WalletObservation": (WalletObservation, {
        "source": "text", "product": "text", "chain": "opt_text", "account": ("obj", "AccountRef"),
        "source_event_id": "opt_text", "transaction_id": "opt_text", "sub_index": "opt_int", "occurrence": "int",
        "action": ("enum", Action), "raw_action": "text", "instrument_id": "opt_text", "market_id": "opt_text",
        "event_id": "opt_text", "outcome_index": "opt_int", "native_quantity": "opt_decimal",
        "native_decimals": "opt_int", "paid": ("obj_tuple", "AssetAmount"), "received": ("obj_tuple", "AssetAmount"),
        "price": "opt_decimal",
        "price_basis": "opt_text", "fee": "labeled", "source_time": "time", "receipt_time": "time",
        "finality": ("enum", ChainFinality), "raw_ref": "text", "parser_version": "text", "category": "opt_text",
        "ambiguities": "text_list", "synthetic": "bool"}),
    "Correction": (Correction, {
        "correction_id": "text", "target_id": "text", "kind": ("enum", CorrectionKind), "recorded_at": "time",
        "reason": "text", "replacement": ("opt_obj", "WalletObservation"),
        "new_finality": ("opt_enum", ChainFinality)}),
    "Mark": (Mark, {"instrument_id": "text", "kind": ("enum", MarkKind), "price": "decimal",
                    "depth": "opt_decimal", "as_of": "time"}),
    "MarkEvidence": (MarkEvidence, {"mark": ("obj", "Mark"), "source": "text", "received_at": "time",
                                    "quote_basis": "text", "evidence_ref": "text"}),
    "CoverageAssertion": (CoverageAssertion, {
        "account_key": "text", "history_complete": "opt_bool", "source": "text", "method_version": "text",
        "known_at": "time", "evidence_ref": "text"}),
    "FlagAssertion": (FlagAssertion, {
        "account_key": "text", "kind": ("enum", FlagKind), "flags": "opt_code_set", "source": "text",
        "method_version": "text", "known_at": "time", "evidence_ref": "text"}),
    "TrialBasis": (TrialBasis, {"count": "count", "source": "text", "prior_receipt_digests": "digest_set"}),
    "ProxyMapping": (ProxyMapping, {
        "mapping_id": "text", "controller": ("obj", "AccountRef"), "account": ("obj", "AccountRef"),
        "relation": ("enum", RelationKind),
        "valid_from": "time", "valid_to": "opt_time", "observed_at": "time", "basis": ("enum", IdentityBasis),
        "evidence_ref": "text"}),
    "MappingRevocation": (MappingRevocation, {"mapping_id": "text", "ended_at": "time", "observed_at": "time",
                                              "evidence_ref": "text"}),
    "AccountRef": (AccountRef, {"product": "text", "address": "text"}),
    "AssetAmount": (AssetAmount, {"asset": "text", "quantity": "decimal"}),
}

# Units of every rule field, bound in the closure beside the rule.
RULE_UNITS: dict[str, str] = {
    "rule_id": "identifier", "version": "identifier",
    "min_independent_events": "count of independent events (markets of one event are one cluster)",
    "min_history_days": "whole days of observed source_time span",
    "min_shrunk_lower": "probability; lower bound of the shrunk per-event win rate, compared as binary64",
    "max_concentration": "share of buy notional in one market",
    "max_round_trip_share": "share of directional trade notional reversed within round_trip_window",
    "max_reward_dependence": "share: rewards / (|realized gross P&L| + rewards)",
    "inactive_after": "microseconds since the latest observed source_time",
    "round_trip_window": "microseconds from buy to reversing sale",
    "min_trade_notional": "cash notional (quantity x price) below which a trade is bait-sized",
    "require_complete_coverage": "boolean",
}


def _where_err(where: str, why: str) -> ReceiptInputError:
    return ReceiptInputError(f"{where}: {why}")


def _encode(kind: object, value: object, where: str) -> object:  # noqa: C901 - one flat dispatch
    if isinstance(kind, tuple):
        tag, arg = kind
        if tag in ("opt_enum", "opt_obj") and value is None:
            return None
        if tag in ("enum", "opt_enum"):
            if not isinstance(value, arg):  # type: ignore[arg-type]
                raise _where_err(where, f"must be a {arg.__name__}")  # type: ignore[attr-defined]
            return value.value  # type: ignore[attr-defined]
        if tag == "obj_tuple":
            if not isinstance(value, tuple):
                raise _where_err(where, "must be a tuple")
            return [_encode_obj(arg, v, f"{where}[{i}]") for i, v in enumerate(value)]  # type: ignore[arg-type]
        return _encode_obj(arg, value, where)  # type: ignore[arg-type]
    if kind.startswith("opt_") and value is None:  # type: ignore[union-attr]
        return None
    base = kind.removeprefix("opt_") if isinstance(kind, str) and kind not in ("opt_code_set",) else kind
    if base == "text":
        if not isinstance(value, str):
            raise _where_err(where, "must be text")
        return value
    if base in ("int", "count"):
        if isinstance(value, bool) or not isinstance(value, int) or (base == "count" and value < 0):
            raise _where_err(where, "must be an integer" + (" >= 0" if base == "count" else ""))
        return value
    if base == "bool":
        if not isinstance(value, bool):
            raise _where_err(where, "must be a boolean")
        return value
    if base == "decimal":
        return decimal_text(exact_decimal(value, name=where))
    if base == "time":
        return utc_text(require_aware(value, where))
    if base == "duration":
        if not isinstance(value, timedelta):
            raise _where_err(where, "must be a timedelta")
        return {"unit": "microsecond", "value": value // timedelta(microseconds=1)}
    if base == "binary64":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _where_err(where, "must be a float or int (it is compared as binary64; a Decimal is refused)")
        f = float(value)
        if not math.isfinite(f):
            raise _where_err(where, "must be finite")
        return {"compare_as": "IEEE754_BINARY64", "value": decimal_text(Decimal(repr(f)))}
    if base == "labeled":
        if not isinstance(value, Labeled):
            raise _where_err(where, "must be Labeled")
        return value.to_dict()
    if base == "text_list":
        if not isinstance(value, tuple) or not all(isinstance(v, str) for v in value):
            raise _where_err(where, "must be a tuple of text")
        return list(value)
    if kind == "opt_code_set":
        if value is None:
            return None
        if not isinstance(value, tuple) or not all(isinstance(v, str) and _CODE.fullmatch(v) for v in value):
            raise _where_err(where, "must be a tuple of flag codes")
        return sorted(set(value))
    if base == "digest_set":
        return sorted(set(value))  # type: ignore[arg-type]
    raise _where_err(where, f"no canonical encoding for kind {kind!r}")


def _encode_obj(name: str, obj: object, where: str = "") -> dict:
    cls, spec = _SPECS[name]
    where = where or name
    if not isinstance(obj, cls):
        raise _where_err(where, f"must be a {cls.__name__}")
    names = [f.name for f in fields(cls)]
    unbound = sorted(set(names) - set(spec))
    if unbound:
        raise ReceiptInputError(f"{name} fields {unbound} have no canonical encoding: the receipt cannot bind them")
    return {n: _encode(spec[n], getattr(obj, n), f"{where}.{n}") for n in names}


def _bad(where: str, why: str) -> MalformedReceiptError:
    return MalformedReceiptError(f"{where}: {why}")


def _decode(kind: object, raw: object, where: str) -> object:  # noqa: C901 - mirrors _encode
    if isinstance(kind, tuple):
        tag, arg = kind
        if tag in ("opt_enum", "opt_obj") and raw is None:
            return None
        if tag in ("enum", "opt_enum"):
            if not isinstance(raw, str):
                raise _bad(where, "must be an enum value")
            try:
                return arg(raw)  # type: ignore[operator]
            except ValueError as exc:
                raise _bad(where, str(exc)) from exc
        if tag == "obj_tuple":
            if not isinstance(raw, list):
                raise _bad(where, "must be a list")
            return tuple(_decode_obj(arg, v, f"{where}[{i}]") for i, v in enumerate(raw))  # type: ignore[arg-type]
        return _decode_obj(arg, raw, where)  # type: ignore[arg-type]
    if kind.startswith("opt_") and raw is None:  # type: ignore[union-attr]
        return None
    base = kind.removeprefix("opt_") if isinstance(kind, str) and kind != "opt_code_set" else kind
    if base == "text":
        if not isinstance(raw, str):
            raise _bad(where, "must be text")
        return raw
    if base in ("int", "count"):
        if isinstance(raw, bool) or not isinstance(raw, int) or (base == "count" and raw < 0):
            raise _bad(where, "must be an integer")
        return raw
    if base == "bool":
        if not isinstance(raw, bool):
            raise _bad(where, "must be a boolean")
        return raw
    if base == "decimal":
        if not isinstance(raw, str):
            raise _bad(where, "must be decimal text")
        return exact_decimal(raw, name=where)
    if base == "time":
        return _decode_time(raw, where)
    if base == "duration":
        if not isinstance(raw, dict) or set(raw) != {"unit", "value"} or raw["unit"] != "microsecond" \
                or isinstance(raw["value"], bool) or not isinstance(raw["value"], int):
            raise _bad(where, "must be {unit: microsecond, value: int}")
        return timedelta(microseconds=raw["value"])
    if base == "binary64":
        if not isinstance(raw, dict) or set(raw) != {"compare_as", "value"} or raw["compare_as"] != "IEEE754_BINARY64" \
                or not isinstance(raw["value"], str):
            raise _bad(where, "must be {compare_as: IEEE754_BINARY64, value: text}")
        return float(exact_decimal(raw["value"], name=where))
    if base == "labeled":
        if not isinstance(raw, dict) or set(raw) != {"value", "basis", "note"} or not isinstance(raw["note"], str) \
                or not isinstance(raw["basis"], str) or not (raw["value"] is None or isinstance(raw["value"], str)):
            raise _bad(where, "must be {value: text|null, basis: text, note: text}")
        value = None if raw["value"] is None else exact_decimal(raw["value"], name=where)
        return Labeled(value, Basis(raw["basis"]), raw["note"])
    if base == "text_list":
        if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
            raise _bad(where, "must be a list of text")
        return tuple(raw)
    if kind == "opt_code_set":
        if raw is None:
            return None
        if not isinstance(raw, list) or not all(isinstance(v, str) and _CODE.fullmatch(v) for v in raw) \
                or raw != sorted(set(raw)):
            raise _bad(where, "must be a sorted list of unique flag codes")
        return tuple(raw)
    if base == "digest_set":
        if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw) or raw != sorted(set(raw)):
            raise _bad(where, "must be a sorted list of unique digests")
        return tuple(raw)
    raise _bad(where, f"no canonical decoding for kind {kind!r}")


def _decode_time(raw: object, where: str) -> datetime:
    """Strict: only the canonical `utc_text` spelling decodes (no space separator, no other offset)."""
    if not isinstance(raw, str):
        raise _bad(where, "must be time text")
    try:
        value = require_aware(datetime.fromisoformat(raw), where)
    except ValueError as exc:
        raise _bad(where, str(exc)) from exc
    if utc_text(value) != raw:
        raise _bad(where, f"{raw!r} is not the canonical UTC spelling {utc_text(value)!r}")
    return value


def _decode_obj(name: str, raw: object, where: str = "") -> Any:
    cls, spec = _SPECS[name]
    where = where or name
    if not isinstance(raw, dict) or set(raw) != set(spec):
        raise _bad(where, f"must have exactly the keys {sorted(spec)}")
    kwargs = {n: _decode(k, raw[n], f"{where}.{n}") for n, k in spec.items()}
    try:
        return cls(**kwargs)
    except (TypeError, ValueError) as exc:
        raise _bad(where, str(exc)) from exc


def content_hash(content: Mapping) -> str:
    """The hash of one canonical content dict, with the repository's one hashing scheme."""
    return sha256_hex(canonical_json(content))


def _key(content: object) -> str:
    return canonical_json(content)


# --- Engine parameters ------------------------------------------------------------------------------

def _binary64_text(x: float) -> str:
    return decimal_text(Decimal(repr(float(x))))


# The modules whose code decides a selection. Their source is hashed into the engine binding at call
# time, so a code change is an ENGINE_MISMATCH, never a silent REPLAY_MISMATCH.
_ENGINE_MODULES: tuple[ModuleType, ...] = (selection, stats, threats, accounting, events, exact, identity,
                                           market_data, timeutil, provenance)


def _source_digest(path: str | None, name: str) -> str:
    if not path:
        raise EngineMismatchError(f"the source of {name} is not readable, so the engine cannot be bound")
    # Line endings are normalized so one commit hashes alike on every checkout (CRLF or LF).
    return provenance.bytes_sha256(Path(path).read_bytes().replace(b"\r\n", b"\n"))


def engine_source_digests() -> dict[str, str]:
    """SHA-256 of each engine module's source as loaded now (not as of import)."""
    out = {m.__name__: _source_digest(getattr(m, "__file__", None), m.__name__) for m in _ENGINE_MODULES}
    out[__name__] = _source_digest(__file__, __name__)
    return dict(sorted(out.items()))


def engine_parameters() -> dict:
    """The engine's versions, implicit parameters and source digests, read from the loaded code at call
    time. A receipt binds them; `verify` and `rebuild` refuse a record whose engine differs."""
    level = inspect.signature(shrunk_rate).parameters["level"].default
    return {
        "engine": ENGINE_VERSION, "accounting": ACCOUNTING_VERSION, "event_schema": EVENT_SCHEMA,
        "wallet_intel": WALLET_INTEL_VERSION,
        "source_sha256": engine_source_digests(), "source_normalization": "CRLF -> LF before hashing",
        "prior": {"method": "stats.fit_beta_prior (method of moments)", "min_candidates": PRIOR_MIN_CANDIDATES,
                  "weak_default": {"alpha": _binary64_text(WEAK_PRIOR.alpha), "beta": _binary64_text(WEAK_PRIOR.beta)},
                  "pool": "every visible candidate with an effective observation at the cutoff"},
        "shrinkage_level": _binary64_text(level),
        "lookback": "ALL_OBSERVATIONS_KNOWN_BY_CUTOFF",
        "inactivity": "INACTIVE when cutoff - latest effective source_time > rule.inactive_after",
        "opening_balance": "UNKNOWN", "cash_flows_observed": False,
        "unknown_coverage": "COVERAGE_UNKNOWN reason; reconstructed as incomplete history",
        "unassessed_flags": "THREAT_UNASSESSED / QUALITY_UNASSESSED reasons (ineligible)",
        "assertion_selection": "per account (coverage) or per account, kind and source (flags): latest known_at "
                               "at or before the cutoff; a tie with different content fails closed",
        "mark_selection": "per instrument: latest (as_of, received_at) received at or before the cutoff; a tie "
                          "with different content fails closed",
        "correction_order": "per target by (recorded_at, correction_id); a log whose append order differs "
                            "fails closed",
        "backfill": "a conflict detected before its identity's first receipt, or an effective or replacement "
                    "observation received after the cutoff, fails closed",
    }


def _same_engine(engine: object) -> bool:
    return isinstance(engine, Mapping) and canonical_json(engine) == canonical_json(engine_parameters())


# --- Closure -----------------------------------------------------------------------------------------

class IdentityStatus(str, Enum):
    EFFECTIVE = "EFFECTIVE"
    WITHDRAWN = "WITHDRAWN"  # retracted or reorged out by a correction recorded by the cutoff
    CONFLICTED = "CONFLICTED"  # named by a conflict detected by the cutoff (reported, never resolved)


class ConflictKind(str, Enum):
    SAME_IDENTITY_DIFFERENT_CONTENT = "SAME_IDENTITY_DIFFERENT_CONTENT"
    TRANSACTION_TIME_MISMATCH = "TRANSACTION_TIME_MISMATCH"


@dataclass(frozen=True)
class _IdentitySnapshot:
    """The proxy mappings touching one account, and their revocations, as known by the cutoff.
    `mappings is None` means UNKNOWN: no registry was supplied (never "no mappings")."""

    mappings: tuple[ProxyMapping, ...] | None
    revocations: tuple[MappingRevocation, ...]
    reason: str = ""

    def to_dict(self) -> dict:
        if self.mappings is None:
            return {"status": "UNKNOWN", "reason": self.reason}
        return {"status": "KNOWN",
                "mappings": sorted((_encode_obj("ProxyMapping", m) for m in self.mappings), key=_key),
                "revocations": sorted((_encode_obj("MappingRevocation", r) for r in self.revocations), key=_key)}

    def knowledge_times(self) -> list[datetime]:
        return [r.observed_at for r in (*(self.mappings or ()), *self.revocations)]


@dataclass(frozen=True)
class _IdentityState:
    """One observation identity received by the cutoff. `conflict_keys` names the conflicts that make it
    CONFLICTED (its own id, or `source|transaction`); it is non-empty exactly when the status is CONFLICTED."""

    observation_id: str
    first_receipt: datetime
    status: IdentityStatus
    effective_content_sha256: str | None
    conflict_keys: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"observation_id": self.observation_id, "first_receipt": utc_text(self.first_receipt),
                "status": self.status.value, "effective_content_sha256": self.effective_content_sha256,
                "conflict_keys": list(self.conflict_keys)}


@dataclass(frozen=True)
class _ConflictRecord:
    """A conflict detected by the cutoff. `versions` is the sorted pair of what disagrees: two semantic
    keys (same identity) or two canonical source times (one transaction)."""

    kind: ConflictKind
    key: str
    versions: tuple[str, str]
    detected_at: datetime

    def to_dict(self) -> dict:
        return {"kind": self.kind.value, "key": self.key, "versions": list(self.versions),
                "detected_at": utc_text(self.detected_at)}


@dataclass(frozen=True)
class _CandidateClosure:
    account: AccountRef
    discoveries: tuple[Candidate, ...]  # sorted; [0] is the first discovery
    identity: _IdentitySnapshot
    coverage: CoverageAssertion
    flags: tuple[FlagAssertion, ...]  # sorted
    identities: tuple[_IdentityState, ...]  # sorted by observation id
    corrections: tuple[tuple[int, Correction], ...]  # (sequence in knowledge order within target), by target
    conflicts: tuple[_ConflictRecord, ...]  # sorted, unique
    effective: tuple[WalletObservation, ...]  # as_known_at(cutoff) order

    @property
    def first(self) -> Candidate:
        return self.discoveries[0]


@dataclass(frozen=True)
class _Closure:
    cutoff: datetime
    label_version: str
    engine: dict
    rule: EligibilityRule
    mark_max_age: timedelta
    trials: TrialBasis
    fdr_q: float
    candidates: tuple[_CandidateClosure, ...]  # sorted by account key
    marks: tuple[MarkEvidence, ...]  # sorted by instrument

    def to_dict(self) -> dict:
        return {
            "schema": CLOSURE_SCHEMA, "cutoff": utc_text(self.cutoff), "label_version": self.label_version,
            "engine": self.engine, "rule": _encode_obj("EligibilityRule", self.rule), "rule_units": dict(RULE_UNITS),
            "mark_freshness": {"max_age": _encode("duration", self.mark_max_age, "mark_max_age"),
                               "applies_to": [MarkKind.EXECUTABLE_BID.value],
                               "never_withdrawable": [MarkKind.LAST_PRINT.value, MarkKind.VENDOR_MARK.value]},
            "trials": _encode_obj("TrialBasis", self.trials),
            "multiple_testing": {"method": "benjamini_hochberg", "q": _encode("binary64", self.fdr_q, "fdr_q"),
                                 "m": "cumulative trials x candidates with an event win rate",
                                 "null": "one-sided binomial against 0.5 per independent event (a screen)"},
            "candidates": [_candidate_to_dict(c) for c in self.candidates],
            "marks": [_encode_obj("MarkEvidence", m) for m in self.marks],
        }


def _obs_entry(o: WalletObservation) -> dict:
    content = _encode_obj("WalletObservation", o)
    return {"observation_id": o.observation_id, "content_sha256": content_hash(content), "content": content}


def _candidate_to_dict(c: _CandidateClosure) -> dict:
    return {
        "account_key": c.account.key, "account": _encode_obj("AccountRef", c.account, "account"),
        "first_discovery": _encode_obj("Candidate", c.first),
        "discoveries": [_encode_obj("Candidate", d) for d in c.discoveries],
        "identity": c.identity.to_dict(),
        "coverage": _encode_obj("CoverageAssertion", c.coverage),
        "flags": [_encode_obj("FlagAssertion", f) for f in c.flags],
        "history": {
            "identities": [i.to_dict() for i in c.identities],
            "corrections": [{"sequence": s, "correction": _encode_obj("Correction", k)} for s, k in c.corrections],
            "conflicts": [x.to_dict() for x in c.conflicts],
            "effective": [_obs_entry(o) for o in c.effective],
        },
    }


def _latest(items: Sequence[Any], name: str, known_at: str, cutoff: datetime) -> Any | None:
    """The item with the latest knowledge time at or before the cutoff; a tie with different content is
    ambiguous. None when nothing is known by the cutoff."""
    known = [i for i in items if getattr(i, known_at) <= cutoff]
    if not known:
        return None
    top = max(getattr(i, known_at) for i in known)
    tied = {_key(_encode_obj(name, i)): i for i in known if getattr(i, known_at) == top}
    if len(tied) > 1:
        raise AmbiguousInputError(f"{len(tied)} different {name} records share knowledge time {utc_text(top)}")
    return next(iter(tied.values()))


def _identity_snapshot(registry: IdentityRegistry | None, account: AccountRef, cutoff: datetime) -> _IdentitySnapshot:
    if registry is None:
        return _IdentitySnapshot(None, (), "no identity registry was supplied")
    mappings = [r for r in registry.records if isinstance(r, ProxyMapping) and r.observed_at <= cutoff
                and account.key in (r.controller.key, r.account.key)]
    ids = {m.mapping_id for m in mappings}
    revocations = [r for r in registry.records if isinstance(r, MappingRevocation) and r.observed_at <= cutoff
                   and r.mapping_id in ids]
    return _IdentitySnapshot(tuple(sorted(mappings, key=lambda m: _key(_encode_obj("ProxyMapping", m)))),
                             tuple(sorted(revocations, key=lambda r: _key(_encode_obj("MappingRevocation", r)))))


def _tx_key(o: WalletObservation | None) -> str | None:
    return None if o is None or not o.transaction_id else f"{o.source}|{o.transaction_id.lower()}"


def _history(log: ObservationLog, account_key: str, cutoff: datetime) -> tuple[tuple[_IdentityState, ...],
                                                                                tuple[tuple[int, Correction], ...],
                                                                                tuple[_ConflictRecord, ...],
                                                                                tuple[WalletObservation, ...]]:
    effective = log.as_known_at(cutoff)
    for o in effective:
        if o.account.key != account_key:
            raise AmbiguousInputError(f"the log for {account_key} holds an observation of {o.account.key}")
        if o.source_time > cutoff:
            raise HindsightError("an observation received by the cutoff describes an event after it")
        if o.receipt_time > cutoff:
            raise BackfillOrderError(f"{o.observation_id}: the copy in force was received after the cutoff "
                                     f"({utc_text(o.receipt_time)}); the log was backfilled out of receipt order")
    known = {oid: log.first_receipt(oid) for oid in log.all_ids() if log.first_receipt(oid) <= cutoff}
    tx_of = {oid: _tx_key(log.version_at(oid, first, include_conflicted=True)) for oid, first in known.items()}
    records = {}
    for x in log.conflicts:
        if x.detected_at > cutoff:
            continue
        first, second = sorted([x.first, x.second])
        rec = _ConflictRecord(ConflictKind(x.kind), x.key, (first, second), x.detected_at)
        records[_key(rec.to_dict())] = rec
    conflicts = tuple(records[k] for k in sorted(records))
    for x in conflicts:
        if x.kind is ConflictKind.SAME_IDENTITY_DIFFERENT_CONTENT:
            ok = x.key in known and known[x.key] <= x.detected_at
        else:
            ok = any(tx_of[oid] == x.key and known[oid] <= x.detected_at for oid in known)
        if not ok:
            raise BackfillOrderError(f"conflict on {x.key} was detected at {utc_text(x.detected_at)}, before any "
                                     f"version it names was received by the cutoff (out-of-order backfill)")
    conflicted = log.conflicted_ids(cutoff)
    identities = []
    for oid in sorted(known):
        keys = tuple(sorted({x.key for x in conflicts if x.key == oid or (
            x.kind is ConflictKind.TRANSACTION_TIME_MISMATCH and x.key == tx_of[oid])}))
        if bool(keys) != (oid in conflicted):
            raise ReceiptInputError(f"{oid}: the conflict records and the log's conflicted set disagree")
        if keys:
            identities.append(_IdentityState(oid, known[oid], IdentityStatus.CONFLICTED, None, keys))
            continue
        version = log.version_at(oid, cutoff)
        if version is None:
            identities.append(_IdentityState(oid, known[oid], IdentityStatus.WITHDRAWN, None, ()))
        else:
            identities.append(_IdentityState(oid, known[oid], IdentityStatus.EFFECTIVE,
                                             content_hash(_encode_obj("WalletObservation", version)), ()))
    want = sorted(i.effective_content_sha256 or "" for i in identities if i.status is IdentityStatus.EFFECTIVE)
    have = sorted(content_hash(_encode_obj("WalletObservation", o)) for o in effective)
    if want != have:
        raise ReceiptInputError("the effective view does not match the per-identity versions")
    per_target: dict[str, list[Correction]] = {}
    for c in log.corrections:  # append order
        if c.recorded_at <= cutoff and c.target_id in known:
            per_target.setdefault(c.target_id, []).append(c)
    corrections = []
    for target in sorted(per_target):
        appended = per_target[target]
        knowledge = sorted(appended, key=lambda c: (c.recorded_at, c.correction_id))
        if appended != knowledge:
            raise BackfillOrderError(f"corrections to {target} were appended out of knowledge (recorded_at) order")
        for seq, c in enumerate(knowledge):
            if c.replacement is not None and c.replacement.receipt_time > cutoff:
                raise BackfillOrderError(f"correction {c.correction_id}: its replacement was received after the cutoff")
            corrections.append((seq, c))
    return tuple(identities), tuple(corrections), conflicts, tuple(effective)


def _effective_rule(rule: EligibilityRule) -> EligibilityRule:
    """The rule exactly as the engine applies it and the closure records it: Decimal thresholds as exact
    Decimals, the float threshold as the binary64 value its canonical text denotes."""
    _encode_obj("EligibilityRule", rule)  # validates every field and refuses an unbound one
    spec = _SPECS["EligibilityRule"][1]
    changes: dict[str, object] = {}
    for f in fields(EligibilityRule):
        value = getattr(rule, f.name)
        if spec[f.name] == "decimal":
            changes[f.name] = exact_decimal(value, name=f.name)
        elif spec[f.name] == "binary64":
            changes[f.name] = float(value)
    return replace(rule, **changes)


def _fdr_q(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < float(value) < 1:
        raise ReceiptInputError("fdr_q must be a float strictly between 0 and 1")
    return float(value)


def _closure_from_inputs(inputs: SelectionInputsV2) -> _Closure:
    cutoff = require_aware(inputs.cutoff, "cutoff")
    _text_field(inputs.label_version, "label_version")
    if not isinstance(inputs.trials, TrialBasis):
        raise MissingInputError("trials must be a TrialBasis")
    if not isinstance(inputs.logs, Mapping):
        raise MissingInputError("logs must map account keys to observation logs")
    rule = _effective_rule(inputs.rule)
    _encode("duration", inputs.mark_max_age, "mark_max_age")
    discoveries: dict[str, list[Candidate]] = {}
    for c in inputs.candidates:
        if not isinstance(c, Candidate):
            raise ReceiptInputError("candidates must be Candidate records")
        if c.discovered_at <= cutoff:
            discoveries.setdefault(c.account.key, []).append(c)
    coverage: dict[str, list[CoverageAssertion]] = {}
    for a in inputs.coverage:
        if not isinstance(a, CoverageAssertion):
            raise ReceiptInputError("coverage must be CoverageAssertion records")
        coverage.setdefault(a.account_key, []).append(a)
    flags: dict[tuple[str, str, str], list[FlagAssertion]] = {}
    for f in inputs.flags:
        if not isinstance(f, FlagAssertion):
            raise ReceiptInputError("flags must be FlagAssertion records")
        flags.setdefault((f.account_key, f.kind.value, f.source), []).append(f)
    out = []
    for key in sorted(discoveries):
        found = sorted(discoveries[key], key=lambda d: _key(_encode_obj("Candidate", d)))
        found.sort(key=lambda d: d.discovered_at)
        if len({(d.account.product, d.account.address) for d in found}) > 1:
            raise AmbiguousInputError(f"discoveries of {key} name different account spellings")
        unique = tuple({_key(_encode_obj("Candidate", d)): d for d in found}.values())
        log = inputs.logs.get(key)
        if not isinstance(log, ObservationLog):
            raise MissingInputError(f"no observation log was supplied for {key} (pass an empty log for no data)")
        cov = _latest(coverage.get(key, []), "CoverageAssertion", "known_at", cutoff)
        if cov is None:
            raise MissingInputError(f"no coverage assertion for {key} is known by the cutoff")
        in_force = [f for (k, _, _), group in sorted(flags.items()) if k == key
                    for f in [_latest(group, "FlagAssertion", "known_at", cutoff)] if f is not None]
        if not any(f.kind is FlagKind.THREAT for f in in_force):
            raise MissingInputError(f"no threat assertion for {key} is known by the cutoff")
        identities, corrections, conflicts, effective = _history(log, key, cutoff)
        out.append(_CandidateClosure(
            unique[0].account, unique, _identity_snapshot(inputs.identity, unique[0].account, cutoff), cov,
            tuple(sorted(in_force, key=lambda f: _key(_encode_obj("FlagAssertion", f)))), identities, corrections,
            conflicts, effective))
    by_instrument: dict[str, list[MarkEvidence]] = {}
    for m in inputs.marks:
        if not isinstance(m, MarkEvidence):
            raise ReceiptInputError("marks must be MarkEvidence records (a bare Mark has no source or receipt time)")
        if m.received_at <= cutoff:
            by_instrument.setdefault(m.mark.instrument_id, []).append(m)
    marks = []
    for instrument in sorted(by_instrument):
        group = by_instrument[instrument]
        top = max((m.mark.as_of, m.received_at) for m in group)
        tied = {_key(_encode_obj("MarkEvidence", m)): m for m in group if (m.mark.as_of, m.received_at) == top}
        if len(tied) > 1:
            raise AmbiguousInputError(f"{len(tied)} different marks for {instrument} share as-of and receipt times")
        marks.append(next(iter(tied.values())))
    return _Closure(cutoff, inputs.label_version, engine_parameters(), rule, inputs.mark_max_age, inputs.trials,
                    _fdr_q(inputs.fdr_q), tuple(out), tuple(marks))


def _check_causal(closure: _Closure) -> None:
    """Every knowledge time in a closure is at or before its cutoff, every copy it binds was received by
    then, and no conflict predates the receipt of what it names. Built closures satisfy this by
    construction; a persisted one that does not is a CAUSALITY_VIOLATION."""
    t = closure.cutoff
    late: list[str] = []
    for c in closure.candidates:
        k = c.account.key
        late += [f"{k}: discovered {utc_text(d.discovered_at)}" for d in c.discoveries if d.discovered_at > t]
        if c.coverage.known_at > t:
            late.append(f"{k}: coverage known {utc_text(c.coverage.known_at)}")
        late += [f"{k}: flags known {utc_text(f.known_at)}" for f in c.flags if f.known_at > t]
        late += [f"{k}: correction {x.correction_id}" for _, x in c.corrections if x.recorded_at > t]
        late += [f"{k}: replacement in {x.correction_id} received {utc_text(x.replacement.receipt_time)}"
                 for _, x in c.corrections if x.replacement is not None and x.replacement.receipt_time > t]
        late += [f"{k}: conflict on {x.key}" for x in c.conflicts if x.detected_at > t]
        late += [f"{k}: identity {i.observation_id}" for i in c.identities if i.first_receipt > t]
        late += [f"{k}: observation {o.observation_id} at {utc_text(o.source_time)}" for o in c.effective
                 if o.source_time > t]
        late += [f"{k}: observation {o.observation_id} received {utc_text(o.receipt_time)}" for o in c.effective
                 if o.receipt_time > t]
        late += [f"{k}: identity record observed {utc_text(w)}" for w in c.identity.knowledge_times() if w > t]
        firsts = {i.observation_id: i.first_receipt for i in c.identities}
        for x in c.conflicts:
            holders = [i for i in c.identities if x.key in i.conflict_keys]
            if x.kind is ConflictKind.SAME_IDENTITY_DIFFERENT_CONTENT:
                early = x.key not in firsts or firsts[x.key] > x.detected_at
            else:
                early = not any(i.first_receipt <= x.detected_at for i in holders)
            if early:
                late.append(f"{k}: conflict on {x.key} detected before what it names was received")
    late += [f"mark {m.mark.instrument_id} received {utc_text(m.received_at)}" for m in closure.marks
             if m.received_at > t]
    if late:
        raise CausalityError("knowledge after the cutoff: " + "; ".join(late))


def _decode_identity(raw: object, where: str) -> _IdentitySnapshot:
    if not isinstance(raw, dict) or raw.get("status") not in ("KNOWN", "UNKNOWN"):
        raise _bad(where, "identity must be KNOWN or UNKNOWN")
    if raw["status"] == "UNKNOWN":
        if set(raw) != {"status", "reason"} or not isinstance(raw["reason"], str):
            raise _bad(where, "an UNKNOWN identity has exactly a reason")
        return _IdentitySnapshot(None, (), raw["reason"])
    if set(raw) != {"status", "mappings", "revocations"} or not isinstance(raw["mappings"], list) \
            or not isinstance(raw["revocations"], list):
        raise _bad(where, "a KNOWN identity has mappings and revocations")
    return _IdentitySnapshot(tuple(_decode_obj("ProxyMapping", m, f"{where}.mappings") for m in raw["mappings"]),
                             tuple(_decode_obj("MappingRevocation", r, f"{where}.revocations")
                                   for r in raw["revocations"]))


def _decode_identity_state(raw: object, where: str) -> _IdentityState:
    keys = {"observation_id", "first_receipt", "status", "effective_content_sha256", "conflict_keys"}
    if not isinstance(raw, dict) or set(raw) != keys:
        raise _bad(where, f"must have exactly the keys {sorted(keys)}")
    oid, digest, ckeys = raw["observation_id"], raw["effective_content_sha256"], raw["conflict_keys"]
    if not isinstance(oid, str) or not oid:
        raise _bad(where, "observation_id must be text")
    status = _decode(("enum", IdentityStatus), raw["status"], f"{where}.status")
    if not isinstance(ckeys, list) or not all(isinstance(k, str) and k for k in ckeys) or ckeys != sorted(set(ckeys)):
        raise _bad(where, "conflict_keys must be a sorted list of unique text")
    if (status is IdentityStatus.CONFLICTED) != bool(ckeys):
        raise _bad(where, "an identity is CONFLICTED exactly when conflict keys name it")
    if status is IdentityStatus.EFFECTIVE:
        if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
            raise _bad(where, "an EFFECTIVE identity needs its content digest")
    elif digest is not None:
        raise _bad(where, "only an EFFECTIVE identity has a content digest")
    return _IdentityState(oid, _decode_time(raw["first_receipt"], f"{where}.first_receipt"), status,  # type: ignore[arg-type]
                          digest, tuple(ckeys))


def _decode_conflict(raw: object, where: str) -> _ConflictRecord:
    if not isinstance(raw, dict) or set(raw) != {"kind", "key", "versions", "detected_at"}:
        raise _bad(where, "must have exactly the keys detected_at, key, kind, versions")
    kind = _decode(("enum", ConflictKind), raw["kind"], f"{where}.kind")
    versions = raw["versions"]
    if not isinstance(raw["key"], str) or not raw["key"] or not isinstance(versions, list) or len(versions) != 2 \
            or not all(isinstance(v, str) for v in versions) or not versions[0] < versions[1]:
        raise _bad(where, "a conflict names its key and a strictly sorted pair of versions")
    if kind is ConflictKind.SAME_IDENTITY_DIFFERENT_CONTENT:
        if not all(_HEX64.fullmatch(v) for v in versions):
            raise _bad(where, "an identity conflict's versions are two semantic keys")
    else:
        for v in versions:
            _decode_time(v, f"{where}.versions")
    return _ConflictRecord(kind, raw["key"], (versions[0], versions[1]),  # type: ignore[arg-type]
                           _decode_time(raw["detected_at"], f"{where}.detected_at"))


def _decode_candidate(raw: object, where: str) -> _CandidateClosure:
    keys = {"account_key", "account", "first_discovery", "discoveries", "identity", "coverage", "flags", "history"}
    if not isinstance(raw, dict) or set(raw) != keys:
        raise _bad(where, f"must have exactly the keys {sorted(keys)}")
    account = _decode_obj("AccountRef", raw["account"], f"{where}.account")
    if not isinstance(raw["discoveries"], list) or not isinstance(raw["flags"], list):
        raise _bad(where, "discoveries and flags must be lists")
    discoveries = tuple(_decode_obj("Candidate", d, f"{where}.discoveries") for d in raw["discoveries"])
    if not discoveries or _key(_encode_obj("Candidate", discoveries[0])) != _key(raw["first_discovery"]):
        raise _bad(where, "first_discovery must be the first of the discoveries")
    history = raw["history"]
    if not isinstance(history, dict) or set(history) != {"identities", "corrections", "conflicts", "effective"} \
            or not all(isinstance(v, list) for v in history.values()):
        raise _bad(f"{where}.history", "must have the lists identities, corrections, conflicts and effective")
    identities = tuple(_decode_identity_state(i, f"{where}.history.identities") for i in history["identities"])
    corrections = []
    for x in history["corrections"]:
        if not isinstance(x, dict) or set(x) != {"sequence", "correction"}:
            raise _bad(f"{where}.history.corrections", "malformed correction record")
        corrections.append((_decode("count", x["sequence"], f"{where}.sequence"),
                            _decode_obj("Correction", x["correction"], f"{where}.history.corrections")))
    conflicts = tuple(_decode_conflict(x, f"{where}.history.conflicts") for x in history["conflicts"])
    effective = []
    for e in history["effective"]:
        if not isinstance(e, dict) or set(e) != {"observation_id", "content_sha256", "content"}:
            raise _bad(f"{where}.history.effective", "malformed effective observation")
        o = _decode_obj("WalletObservation", e["content"], f"{where}.history.effective")
        if o.observation_id != e["observation_id"] or content_hash(e["content"]) != e["content_sha256"]:
            raise _bad(f"{where}.history.effective", f"{e['observation_id']}: id or content hash does not match")
        effective.append(o)
    return _CandidateClosure(
        account, discoveries, _decode_identity(raw["identity"], f"{where}.identity"),
        _decode_obj("CoverageAssertion", raw["coverage"], f"{where}.coverage"),
        tuple(_decode_obj("FlagAssertion", f, f"{where}.flags") for f in raw["flags"]), identities,
        tuple(corrections), conflicts, tuple(effective))


_CLOSURE_KEYS = {"schema", "cutoff", "label_version", "engine", "rule", "rule_units", "mark_freshness", "trials",
                 "multiple_testing", "candidates", "marks"}


def _closure_from_dict(raw: object) -> _Closure:
    if not isinstance(raw, dict) or set(raw) != _CLOSURE_KEYS or raw.get("schema") != CLOSURE_SCHEMA:
        raise _bad("closure", f"must be a {CLOSURE_SCHEMA} closure with exactly the keys {sorted(_CLOSURE_KEYS)}")
    freshness, mt = raw["mark_freshness"], raw["multiple_testing"]
    if not isinstance(freshness, dict) or set(freshness) != {"max_age", "applies_to", "never_withdrawable"}:
        raise _bad("closure.mark_freshness", "malformed")
    if not isinstance(mt, dict) or set(mt) != {"method", "q", "m", "null"}:
        raise _bad("closure.multiple_testing", "malformed")
    if not isinstance(raw["label_version"], str) or not isinstance(raw["engine"], dict) \
            or not isinstance(raw["candidates"], list) or not isinstance(raw["marks"], list):
        raise _bad("closure", "label_version must be text, engine a mapping, candidates and marks lists")
    closure = _Closure(
        _decode_time(raw["cutoff"], "closure.cutoff"), raw["label_version"], dict(raw["engine"]),
        _decode_obj("EligibilityRule", raw["rule"], "closure.rule"),
        _decode("duration", freshness["max_age"], "closure.mark_freshness.max_age"),  # type: ignore[arg-type]
        _decode_obj("TrialBasis", raw["trials"], "closure.trials"),
        _decode("binary64", mt["q"], "closure.multiple_testing.q"),  # type: ignore[arg-type]
        tuple(_decode_candidate(c, f"closure.candidates[{i}]") for i, c in enumerate(raw["candidates"])),
        tuple(_decode_obj("MarkEvidence", m, f"closure.marks[{i}]") for i, m in enumerate(raw["marks"])))
    # Canonical JSON, not Python equality: 5 == 5.0 and 0 == False must not pass as the same closure.
    if canonical_json(closure.to_dict()) != canonical_json(raw):
        raise _bad("closure", "does not re-encode to itself (non-canonical spelling, type or value)")
    _fdr_q(closure.fdr_q)
    _check_canonical_order(closure)
    return closure


def _strictly_sorted(keys: Sequence[Any], where: str) -> None:
    if any(not a < b for a, b in zip(keys, keys[1:])):
        raise _bad(where, "is not in canonical order, or repeats an entry")


def _check_canonical_order(closure: _Closure) -> None:  # noqa: C901 - one list of structural checks
    """Unordered collections are stored sorted and unique, ordered ones in their semantic order, and the
    history's parts agree with each other, so one closure has exactly one serialization and digest."""
    _strictly_sorted([c.account.key for c in closure.candidates], "closure.candidates")
    _strictly_sorted([m.mark.instrument_id for m in closure.marks], "closure.marks")
    for c in closure.candidates:
        w = f"closure.candidates[{c.account.key}]"
        _strictly_sorted([(d.discovered_at, _key(_encode_obj("Candidate", d))) for d in c.discoveries],
                         f"{w}.discoveries")
        if any(d.account.key != c.account.key for d in c.discoveries):
            raise _bad(w, "a discovery names another account")
        _strictly_sorted([_key(_encode_obj("FlagAssertion", f)) for f in c.flags], f"{w}.flags")
        if len({(f.kind, f.source) for f in c.flags}) != len(c.flags) \
                or any(f.account_key != c.account.key for f in c.flags) or c.coverage.account_key != c.account.key:
            raise _bad(w, "assertions must name this account, with one flag assertion per kind and source")
        if not any(f.kind is FlagKind.THREAT for f in c.flags):
            raise _bad(w, "no threat assertion")
        if c.identity.mappings is not None:
            ids = {m.mapping_id for m in c.identity.mappings}
            if any(c.account.key not in (m.controller.key, m.account.key) for m in c.identity.mappings) \
                    or any(r.mapping_id not in ids for r in c.identity.revocations):
                raise _bad(w, "the identity snapshot holds a record that does not concern this account")
        _strictly_sorted([i.observation_id for i in c.identities], f"{w}.history.identities")
        known = {i.observation_id for i in c.identities}
        _strictly_sorted([(x.target_id, s) for s, x in c.corrections], f"{w}.history.corrections")
        for target in {x.target_id for _, x in c.corrections}:
            mine = [(s, x) for s, x in c.corrections if x.target_id == target]
            if target not in known or [s for s, _ in mine] != list(range(len(mine))) \
                    or [x for _, x in mine] != sorted((x for _, x in mine), key=lambda x: (x.recorded_at, x.correction_id)):
                raise _bad(w, f"corrections to {target} are not numbered 0..n-1 in knowledge order")
        _strictly_sorted([_key(x.to_dict()) for x in c.conflicts], f"{w}.history.conflicts")
        named = {k for i in c.identities for k in i.conflict_keys}
        if named != {x.key for x in c.conflicts}:
            raise _bad(w, "conflict records and CONFLICTED identities do not name the same conflicts")
        for x in c.conflicts:
            if x.kind is ConflictKind.SAME_IDENTITY_DIFFERENT_CONTENT and not any(
                    i.observation_id == x.key and x.key in i.conflict_keys for i in c.identities):
                raise _bad(w, f"identity conflict {x.key} does not mark its own identity CONFLICTED")
        for i in c.identities:
            for k in i.conflict_keys:
                if k != i.observation_id and not any(
                        x.key == k and x.kind is ConflictKind.TRANSACTION_TIME_MISMATCH for x in c.conflicts):
                    raise _bad(w, f"{i.observation_id} names conflict {k}, which is not a transaction conflict")
        order = [(o.source_time, o.observation_id) for o in c.effective]
        if order != sorted(order):
            raise _bad(w, "effective observations are not in (source_time, observation_id) order")
        want = sorted(i.effective_content_sha256 or "" for i in c.identities if i.status is IdentityStatus.EFFECTIVE)
        have = sorted(content_hash(_encode_obj("WalletObservation", o)) for o in c.effective)
        if want != have:
            raise _bad(w, "effective observations do not match the identity records")


# --- Engine run --------------------------------------------------------------------------------------

def _run(closure: _Closure) -> tuple[tuple[SelectionRecord, ...], BetaPrior]:
    visible = [c.first for c in closure.candidates]
    views = {c.account.key: c.effective for c in closure.candidates}
    coverage = {c.account.key: c.coverage.history_complete is True for c in closure.candidates}
    flags: dict[str, list[str]] = {}
    extra: dict[str, list[str]] = {}
    for c in closure.candidates:
        k = c.account.key
        reasons = ["COVERAGE_UNKNOWN"] if c.coverage.history_complete is None else []
        threat: set[str] = set()
        quality: set[str] = set()
        unassessed = []
        for f in c.flags:
            if f.flags is None:
                unassessed.append(f"{f.kind.value}_UNASSESSED:{f.source}")
            elif f.kind is FlagKind.THREAT:
                threat.update(f.flags)
            else:
                quality.update(f.flags)
        flags[k] = sorted(threat)
        extra[k] = reasons + [f"QUALITY:{q}" for q in sorted(quality)] + sorted(unassessed)
    marks = {m.mark.instrument_id: m.mark for m in closure.marks}
    return decide(closure.cutoff, visible, views, coverage=coverage, marks=marks, rule=closure.rule,
                  mark_max_age=closure.mark_max_age, flags=flags, extra_reasons=extra,
                  prior_min_candidates=closure.engine["prior"]["min_candidates"])


def _record_dict(r: SelectionRecord) -> dict:
    return {"account": r.account_key, "discovered_at": utc_text(r.discovered_at), "status": r.status.value,
            "reasons": list(r.reasons), "observations_used": r.observations_used,
            "last_observed_event": None if r.last_observed_event is None else utc_text(r.last_observed_event),
            "dimensions": r.dimensions}


def _outcome(records: Sequence[SelectionRecord], prior: BetaPrior, trials: int, q: float) -> dict:
    by_status = {s.value: sum(1 for r in records if r.status is s) for s in CandidateStatus}
    mt = multiple_testing(SimpleNamespace(records=records, trials=trials), q=q)  # type: ignore[arg-type]
    return {"records": [_record_dict(r) for r in records],
            "multiple_testing": {"q": _binary64_text(mt.q), "trials": mt.trials, "hypotheses": mt.hypotheses,
                                 "p_values": dict(sorted(mt.p_values.items())), "survivors": sorted(mt.survivors),
                                 "note": mt.note},
            "prior": {"alpha": _binary64_text(prior.alpha), "beta": _binary64_text(prior.beta), "source": prior.source},
            "denominators": {"visible_candidates": len(records),
                             "with_data": sum(1 for r in records if r.status is not CandidateStatus.NO_DATA),
                             "by_status": by_status}}


# --- Receipt -----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SelectionReceiptV2:
    closure: dict
    closure_digest: str  # the v2 selection digest: binds the complete causal closure
    outcome: dict
    outcome_digest: str
    downstream: dict  # slot -> NOT_BOUND or a binding dict
    receipt_digest: str  # binds schema, closure digest, outcome digest and downstream bindings
    records: tuple[SelectionRecord, ...]
    trials: int

    @property
    def eligible(self) -> tuple[str, ...]:
        return tuple(r.account_key for r in self.records if r.status is CandidateStatus.ELIGIBLE)

    def to_dict(self) -> dict:
        return json.loads(canonical_json({
            "schema": RECEIPT_SCHEMA, "replayability": REPLAYABILITY_V2, "closure": self.closure,
            "closure_digest": self.closure_digest, "outcome": self.outcome, "outcome_digest": self.outcome_digest,
            "downstream": self.downstream, "receipt_digest": self.receipt_digest}))


def _receipt_digest(closure_digest: str, outcome_digest: str, downstream: Mapping) -> str:
    return sha256_hex(canonical_json({"schema": RECEIPT_SCHEMA, "closure_digest": closure_digest,
                                      "outcome_digest": outcome_digest, "downstream": downstream}))


def _assemble(closure: _Closure, downstream: Mapping[str, dict]) -> SelectionReceiptV2:
    _check_causal(closure)
    records, prior = _run(closure)
    closure_dict = json.loads(canonical_json(closure.to_dict()))
    outcome = json.loads(canonical_json(_outcome(records, prior, closure.trials.count, closure.fdr_q)))
    cd, od = content_hash(closure_dict), content_hash(outcome)
    down = json.loads(canonical_json(dict(downstream)))
    return SelectionReceiptV2(closure_dict, cd, outcome, od, down, _receipt_digest(cd, od, down), records,
                              closure.trials.count)


def build_receipt(inputs: SelectionInputsV2) -> SelectionReceiptV2:
    """The v2 receipt of one point-in-time selection, every downstream slot NOT_BOUND."""
    return _assemble(_closure_from_inputs(inputs), {s.value: dict(NOT_BOUND) for s in DownstreamSlot})


def _decode_downstream(raw: object, selection_digest: str) -> dict:
    if not isinstance(raw, dict) or set(raw) != {s.value for s in DownstreamSlot}:
        raise _bad("downstream", f"must name exactly the slots {[s.value for s in DownstreamSlot]}")
    out = {}
    for slot in DownstreamSlot:
        entry = raw[slot.value]
        if entry == NOT_BOUND:
            out[slot.value] = dict(NOT_BOUND)
            continue
        if not isinstance(entry, dict) or set(entry) != {"status", "schema", "selection_digest", "closure",
                                                         "closure_digest", "report_digest"} \
                or entry["status"] != "BOUND":
            raise _bad(f"downstream.{slot.value}", "must be NOT_BOUND or a full binding")
        binding = DownstreamBinding(slot, entry["schema"], entry["selection_digest"], entry["closure"],
                                    entry["report_digest"])
        if canonical_json(binding.to_dict()) != canonical_json(entry):
            raise DownstreamBindingError(f"{slot.value}: closure digest does not match its closure")
        if binding.selection_digest != selection_digest:
            raise DownstreamBindingError(f"{slot.value}: bound to another selection")
        out[slot.value] = entry
    return out


def bind_downstream(receipt: SelectionReceiptV2, binding: DownstreamBinding) -> SelectionReceiptV2:
    """A new receipt with `binding` in its slot. The selection closure and its digest are unchanged; the
    receipt digest changes. A slot already bound to a different closure is never replaced."""
    if binding.selection_digest != receipt.closure_digest:
        raise DownstreamBindingError("the binding names a different selection closure digest")
    current = receipt.downstream[binding.slot.value]
    entry = binding.to_dict()
    if canonical_json(current) == canonical_json(entry):
        return receipt
    if current != NOT_BOUND:
        raise DownstreamBindingError(f"{binding.slot.value} is already bound to another closure")
    down = {**receipt.downstream, binding.slot.value: entry}
    return SelectionReceiptV2(receipt.closure, receipt.closure_digest, receipt.outcome, receipt.outcome_digest,
                              down, _receipt_digest(receipt.closure_digest, receipt.outcome_digest, down),
                              receipt.records, receipt.trials)


def rebuild(record: Mapping) -> SelectionReceiptV2:
    """Re-derive a receipt from a persisted v2 record alone: decode the closure (it must re-encode to
    itself), refuse it when the loaded engine differs from the one it names, re-run the engine and
    re-hash. Raises LegacyReceiptError for a v1 record and EngineMismatchError for another engine."""
    if not isinstance(record, Mapping):
        raise _bad("receipt", "must be a mapping")
    if record.get("version") == SELECTION_VERSION:
        raise LegacyReceiptError(f"a {SELECTION_VERSION} record is {LEGACY_V1_STATUS}; it is never upgraded")
    if record.get("schema") != RECEIPT_SCHEMA:
        raise _bad("receipt", f"unrecognized schema {record.get('schema')!r}")
    closure = _closure_from_dict(record.get("closure"))
    if not _same_engine(closure.engine):
        raise EngineMismatchError("the record names another engine (versions, parameters or source)")
    selection_digest = content_hash(record["closure"])
    return _assemble(closure, _decode_downstream(record.get("downstream"), selection_digest))


# --- Verification ------------------------------------------------------------------------------------

class VerifyStatus(str, Enum):
    VERIFIED = "VERIFIED"
    LEGACY_INCOMPLETE = "LEGACY_INCOMPLETE"  # a v1 record: never fully replayable, never upgraded
    MALFORMED = "MALFORMED"
    TAMPERED = "TAMPERED"  # a stored digest does not match its content
    ENGINE_MISMATCH = "ENGINE_MISMATCH"  # the running code's versions or implicit parameters differ
    CAUSALITY_VIOLATION = "CAUSALITY_VIOLATION"  # the closure claims knowledge from after its cutoff
    REPLAY_MISMATCH = "REPLAY_MISMATCH"  # re-running the engine on the closure gives another outcome
    SOURCE_MISMATCH = "SOURCE_MISMATCH"  # rebuilding from the supplied sources gives another closure


@dataclass(frozen=True)
class Verification:
    status: VerifyStatus
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status is VerifyStatus.VERIFIED


_RECEIPT_KEYS = {"schema", "replayability", "closure", "closure_digest", "outcome", "outcome_digest", "downstream",
                 "receipt_digest"}


def verify(record: object, *, inputs: SelectionInputsV2 | None = None) -> Verification:
    """VERIFIED, or exactly one deterministic failure; it never raises.

    Without `inputs` this proves **internal consistency only**: digests match contents, the engine is
    the loaded one, the closure is canonical and causal, and replaying it gives the stored outcome. A
    forger who rewrites a closure and recomputes every digest also passes, so the `receipt_digest`
    must be pinned somewhere else (a ledger row, a PR, a report). With `inputs`, the receipt must also
    equal the one rebuilt from those sources, which catches a consistent forgery as SOURCE_MISMATCH."""
    try:
        result = _verify_record(record)
    except Exception as exc:  # noqa: BLE001 - verify is total: any unexpected shape is MALFORMED
        return Verification(VerifyStatus.MALFORMED, f"{type(exc).__name__}: {exc}")
    if not result.ok or inputs is None:
        return result
    try:
        fresh = build_receipt(inputs)
    except Exception as exc:  # noqa: BLE001 - sources that do not build are a mismatch, not a crash
        return Verification(VerifyStatus.SOURCE_MISMATCH, f"the sources do not build: {type(exc).__name__}: {exc}")
    if fresh.closure_digest != record["closure_digest"]:  # type: ignore[index]
        return Verification(VerifyStatus.SOURCE_MISMATCH, "the sources give another closure")
    return result


def _verify_record(record: object) -> Verification:
    if not isinstance(record, Mapping):
        return Verification(VerifyStatus.MALFORMED, "not a mapping")
    if record.get("version") == SELECTION_VERSION and "schema" not in record:
        return Verification(VerifyStatus.LEGACY_INCOMPLETE, "v1 digest does not bind: " + "; ".join(LEGACY_V1_UNBOUND))
    if record.get("schema") != RECEIPT_SCHEMA:
        return Verification(VerifyStatus.MALFORMED, f"unrecognized schema {record.get('schema')!r}")
    if set(record) != _RECEIPT_KEYS or record.get("replayability") != REPLAYABILITY_V2:
        return Verification(VerifyStatus.MALFORMED, f"a v2 receipt has exactly the keys {sorted(_RECEIPT_KEYS)}")
    closure_ok = content_hash(record["closure"]) == record["closure_digest"]
    outcome_ok = content_hash(record["outcome"]) == record["outcome_digest"]
    receipt_ok = _receipt_digest(record["closure_digest"], record["outcome_digest"],
                                 record["downstream"]) == record["receipt_digest"]
    if not (closure_ok and outcome_ok and receipt_ok):
        return Verification(VerifyStatus.TAMPERED, f"closure={closure_ok} outcome={outcome_ok} receipt={receipt_ok}")
    engine = record["closure"].get("engine") if isinstance(record["closure"], Mapping) else None
    if not _same_engine(engine):
        if engine == engine_parameters():  # equal only under Python's lax equality (5 == 5.0, 0 == False)
            return Verification(VerifyStatus.MALFORMED, "the engine binding is not canonically spelled")
        return Verification(VerifyStatus.ENGINE_MISMATCH, "the loaded engine's versions, parameters or source differ")
    try:
        rebuilt = rebuild(record)
    except CausalityError as exc:
        return Verification(VerifyStatus.CAUSALITY_VIOLATION, str(exc))
    except EngineMismatchError as exc:
        return Verification(VerifyStatus.ENGINE_MISMATCH, str(exc))
    except DownstreamBindingError as exc:
        return Verification(VerifyStatus.TAMPERED, str(exc))
    except (ReceiptInputError, KeyError, TypeError, ValueError) as exc:
        return Verification(VerifyStatus.MALFORMED, f"{type(exc).__name__}: {exc}")
    if canonical_json(rebuilt.outcome) != canonical_json(record["outcome"]):
        return Verification(VerifyStatus.REPLAY_MISMATCH, "re-running the engine on the closure gives another outcome")
    if rebuilt.receipt_digest != record["receipt_digest"]:
        return Verification(VerifyStatus.TAMPERED, "the rebuilt receipt digest differs")
    return Verification(VerifyStatus.VERIFIED)


def load_receipt(record: Mapping) -> SelectionReceiptV2:
    """A verified v2 receipt, or an error. A v1 record raises LegacyReceiptError: never upgraded."""
    result = verify(record)
    if result.status is VerifyStatus.LEGACY_INCOMPLETE:
        raise LegacyReceiptError(result.detail)
    if not result.ok:
        raise ReceiptInputError(f"{result.status.value}: {result.detail}")
    return rebuild(record)
