"""Analysis import for the manual AI bridge (#192, ADR 0049): the inbound half.

The owner pastes an assistant's whole reply, prose included. This module finds the one JSON
object carrying `"schema": "market-edge-intel-analysis/1"`, then validates it strictly:
- every key is known and typed;
- the packet id, hash and event id echo a packet we generated;
- outcome, evidence and claim ids exist in that packet;
- every probability range has 0 < low <= probability <= high < 1, or the outcome abstains;
- no price, fee or ticker key appears anywhere (Kalshi data never comes back through here).

Invalid input is rejected with readable reasons, never repaired by guessing. A valid analysis
is stored as an UNVALIDATED model interpretation (or owner judgment). It is provisional: no
calibration history exists for it.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

from .contracts import MAX_ANALYSIS_BYTES, ForecastBasis
from .packet import ANALYSIS_SCHEMA, Packet

TOP_KEYS = {"schema", "packet_id", "packet_sha256", "event_id", "assistant", "basis", "market_price_seen",
            "summary", "outcomes", "claims"}
REQUIRED_TOP = {"schema", "packet_id", "packet_sha256", "event_id", "outcomes"}
OUTCOME_KEYS = {"outcome_id", "abstain", "probability", "low", "high", "reasoning", "key_evidence_ids", "main_risk"}
CLAIM_KEYS = {"claim_id", "assessment", "evidence_ids"}
ASSESSMENTS = {"SUPPORTED", "CONTRADICTED", "UNVERIFIED"}
FORBIDDEN_KEY = re.compile(r"(price|ticker|fee|bid|ask|odds|stake|size|order|kalshi)", re.I)
PLACEHOLDER = re.compile(r"^<.*>$", re.S)


class AnalysisError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class OutcomeJudgment:
    outcome_id: str
    abstain: bool
    probability: float | None
    low: float | None
    high: float | None
    reasoning: str
    key_evidence_ids: tuple[str, ...]  # packet-local ids (E1..)
    main_risk: str


@dataclass(frozen=True)
class ClaimJudgment:
    claim_id: str
    assessment: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class Analysis:
    packet_id: str
    packet_sha256: str
    event_id: str
    assistant: str
    basis: ForecastBasis
    market_price_seen: bool
    summary: str
    outcomes: tuple[OutcomeJudgment, ...]
    claims: tuple[ClaimJudgment, ...]
    canonical_json: str  # the validated object, canonical JSON (stored and hashed)


def _candidates(text: str) -> list[str]:
    """JSON object texts in a pasted reply: fenced blocks first, then balanced top-level objects."""
    out = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    depth, start, in_str, esc = 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                out.append(text[start:i + 1])
                start = None
    return out


def extract_object(pasted: str) -> dict:
    """The single analysis object in a pasted reply. Raises AnalysisError when there is none or several."""
    if len(pasted.encode("utf-8", "replace")) > MAX_ANALYSIS_BYTES:
        raise AnalysisError([f"the pasted text is larger than {MAX_ANALYSIS_BYTES // 1024} KiB"])
    found: dict[str, dict] = {}
    for blob in _candidates(pasted):
        try:
            obj = json.loads(blob, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
        except (ValueError, RecursionError):
            continue
        if isinstance(obj, dict) and obj.get("schema") == ANALYSIS_SCHEMA:
            found[json.dumps(obj, sort_keys=True)] = obj
    if not found:
        raise AnalysisError([f"no JSON object with \"schema\": \"{ANALYSIS_SCHEMA}\" was found in the pasted text"])
    if len(found) > 1:
        raise AnalysisError(["the pasted text holds more than one different analysis object; paste one"])
    return next(iter(found.values()))


def _forbidden_keys(obj, path: str = "") -> list[str]:
    bad = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if FORBIDDEN_KEY.search(str(k)) and k != "market_price_seen":
                bad.append(f"{path}{k}")
            bad.extend(_forbidden_keys(v, f"{path}{k}."))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad.extend(_forbidden_keys(v, f"{path}{i}."))
    return bad


def _prob(v, name: str, problems: list[str]) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        problems.append(f"{name} must be a number between 0 and 1")
        return None
    if not 0.0 < float(v) < 1.0:
        problems.append(f"{name} must be strictly between 0 and 1 (got {v})")
        return None
    return float(v)


def _text(v, name: str, limit: int, problems: list[str], *, required: bool = False) -> str:
    if v is None or v == "":
        if required:
            problems.append(f"{name} is required")
        return ""
    if not isinstance(v, str):
        problems.append(f"{name} must be text")
        return ""
    if PLACEHOLDER.match(v.strip()):
        problems.append(f"{name} still holds the template placeholder {v.strip()[:40]!r}")
        return ""
    if len(v) > limit:
        problems.append(f"{name} is longer than {limit} characters")
        return v[:limit]
    return v


def validate(obj: dict, packet: Packet, *, allow_owner_basis: bool = True) -> Analysis:
    problems: list[str] = []
    if not isinstance(obj, dict):
        raise AnalysisError(["the analysis must be a JSON object"])
    unknown = set(obj) - TOP_KEYS
    if unknown:
        problems.append(f"unknown keys: {sorted(unknown)}")
    missing = REQUIRED_TOP - set(obj)
    if missing:
        problems.append(f"missing keys: {sorted(missing)}")
    bad = _forbidden_keys(obj)
    if bad:
        problems.append(f"price, fee, ticker or order fields are not accepted here: {bad[:5]}")
    if obj.get("packet_id") != packet.packet_id:
        problems.append("packet_id does not match the packet this analysis is for")
    if obj.get("packet_sha256") != packet.packet_sha256:
        problems.append("packet_sha256 does not match: the packet was edited or this is for another packet")
    if obj.get("event_id") != packet.event_id:
        problems.append("event_id does not match the packet's event")

    basis_raw = obj.get("basis", "AI_ASSISTED_UNVALIDATED")
    try:
        basis = ForecastBasis(basis_raw)
    except ValueError:
        problems.append(f"basis must be AI_ASSISTED_UNVALIDATED or OWNER_JUDGMENT (got {basis_raw!r})")
        basis = ForecastBasis.AI_ASSISTED_UNVALIDATED
    if basis not in (ForecastBasis.AI_ASSISTED_UNVALIDATED, ForecastBasis.OWNER_JUDGMENT) or \
            (basis is ForecastBasis.OWNER_JUDGMENT and not allow_owner_basis):
        problems.append(f"basis {basis.value} cannot be imported through the bridge")
    seen = obj.get("market_price_seen", None)
    if seen is not None and not isinstance(seen, bool):
        problems.append("market_price_seen must be true or false")
    assistant = _text(obj.get("assistant"), "assistant", 60, problems) or (
        "owner" if basis is ForecastBasis.OWNER_JUDGMENT else "unspecified")
    summary = _text(obj.get("summary"), "summary", 2000, problems)

    outcomes_raw = obj.get("outcomes")
    outcomes: list[OutcomeJudgment] = []
    if not isinstance(outcomes_raw, list) or not outcomes_raw:
        problems.append("outcomes must be a non-empty list")
        outcomes_raw = []
    seen_ids: set[str] = set()
    valid_e = set(packet.evidence_ids)
    for i, o in enumerate(outcomes_raw[:50]):
        where = f"outcomes[{i}]"
        if not isinstance(o, dict):
            problems.append(f"{where} must be an object")
            continue
        unknown = set(o) - OUTCOME_KEYS
        if unknown:
            problems.append(f"{where}: unknown keys {sorted(unknown)}")
        oid = o.get("outcome_id")
        if oid not in packet.outcome_ids:
            problems.append(f"{where}: outcome_id {oid!r} is not in the packet")
            continue
        if oid in seen_ids:
            problems.append(f"{where}: outcome_id {oid!r} appears twice")
            continue
        seen_ids.add(oid)
        abstain = o.get("abstain", False)
        if not isinstance(abstain, bool):
            problems.append(f"{where}: abstain must be true or false")
            abstain = False
        p = _prob(o.get("probability"), f"{where}.probability", problems)
        lo = _prob(o.get("low"), f"{where}.low", problems)
        hi = _prob(o.get("high"), f"{where}.high", problems)
        if abstain:
            p = lo = hi = None
        else:
            if p is None:
                problems.append(f"{where}: give a probability, or set abstain to true")
            if (lo is None) != (hi is None):
                problems.append(f"{where}: give both low and high, or neither")
            if p is not None and lo is not None and hi is not None and not (lo <= p <= hi):
                problems.append(f"{where}: need low <= probability <= high (got {lo}, {p}, {hi})")
        ev_ids = o.get("key_evidence_ids", [])
        if not isinstance(ev_ids, list) or not all(isinstance(x, str) for x in ev_ids):
            problems.append(f"{where}: key_evidence_ids must be a list of ids like \"E1\"")
            ev_ids = []
        unknown_ev = [x for x in ev_ids if x not in valid_e]
        if unknown_ev:
            problems.append(f"{where}: unknown evidence ids {unknown_ev[:5]}")
        outcomes.append(OutcomeJudgment(
            outcome_id=oid, abstain=abstain, probability=p, low=lo, high=hi,
            reasoning=_text(o.get("reasoning"), f"{where}.reasoning", 4000, problems),
            key_evidence_ids=tuple(x for x in ev_ids if x in valid_e),
            main_risk=_text(o.get("main_risk"), f"{where}.main_risk", 1000, problems),
        ))

    claims: list[ClaimJudgment] = []
    claims_raw = obj.get("claims", [])
    if not isinstance(claims_raw, list):
        problems.append("claims must be a list")
        claims_raw = []
    for i, c in enumerate(claims_raw[:200]):
        where = f"claims[{i}]"
        if not isinstance(c, dict) or set(c) - CLAIM_KEYS:
            problems.append(f"{where} must be an object with claim_id, assessment, evidence_ids")
            continue
        if c.get("claim_id") not in packet.claim_ids:
            problems.append(f"{where}: claim_id {c.get('claim_id')!r} is not in the packet")
            continue
        if c.get("assessment") not in ASSESSMENTS:
            problems.append(f"{where}: assessment must be one of {sorted(ASSESSMENTS)}")
            continue
        ids = c.get("evidence_ids", [])
        if not isinstance(ids, list) or any(x not in valid_e for x in ids):
            problems.append(f"{where}: evidence_ids must list ids from the packet")
            continue
        claims.append(ClaimJudgment(c["claim_id"], c["assessment"], tuple(ids)))

    if problems:
        raise AnalysisError(problems)
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return Analysis(
        packet_id=packet.packet_id, packet_sha256=packet.packet_sha256, event_id=packet.event_id,
        assistant=assistant, basis=basis, market_price_seen=bool(seen),
        summary=summary, outcomes=tuple(outcomes), claims=tuple(claims), canonical_json=canonical,
    )


def import_pasted(pasted: str, packet_lookup) -> Analysis:
    """Find, match and validate the analysis in a pasted reply. `packet_lookup(packet_id)` returns
    the stored Packet or None."""
    obj = extract_object(pasted)
    packet = packet_lookup(obj.get("packet_id"))
    if packet is None:
        raise AnalysisError([f"packet {obj.get('packet_id')!r} was not generated here (or its record is missing)"])
    return validate(obj, packet)
