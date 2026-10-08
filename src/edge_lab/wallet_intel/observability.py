"""Typed source capabilities and the research/execution eligibility split (W1, ADR 0045).

The prose matrix with every URL is `docs/research/WALLET_SOURCE_MATRIX.md`; a test keeps the two in
agreement. Reuses `sources.AccessTier` and `sources.SourceStatus`. No wallet source is registered in
`sources.REGISTRY` yet: registration comes with an approved collector (W10), never with fixtures.

Every source is PLANNED or BLOCKED here, and every one is `execution_permitted=False`. Observation is
not permission to trade: research eligibility and execution eligibility are separate answers, so an
unsupported venue blocks execution without falsifying a research result.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..sources import AccessTier, SourceStatus

MATRIX_VERSION = "wallet-source-matrix-2026-10-07"


class Fact(str, Enum):
    """A capability as the dated documentation states it. Both DOCUMENTED_* values are class
    DOCUMENTED in the matrix; UNKNOWN means the documentation read does not settle it."""

    DOCUMENTED_YES = "DOCUMENTED_YES"
    DOCUMENTED_NO = "DOCUMENTED_NO"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SourceCapability:
    source_id: str
    product: str
    access_tier: AccessTier
    status: SourceStatus
    public_account_history: Fact  # can arbitrary accounts' actions be read publicly?
    per_fill_identifier: Fact
    finality_documented: Fact
    authentication_required: Fact
    research_verdict: str  # FIRST_SOURCE | CANDIDATE_LATER | NOT_A_LEADER_SOURCE | FOLLOWER_VENUE_ONLY
    execution_permitted: bool = False
    fixture_only: bool = True


Y, N, U = Fact.DOCUMENTED_YES, Fact.DOCUMENTED_NO, Fact.UNKNOWN
MATRIX: dict[str, SourceCapability] = {c.source_id: c for c in (
    # source, product, tier, status, public history, per-fill id, finality, auth, verdict
    SourceCapability("polymarket_data_api_v2", "polymarket_international", AccessTier.OFFICIAL_API,
                     SourceStatus.PLANNED, Y, N, U, N, "FIRST_SOURCE"),
    SourceCapability("polymarket_us", "polymarket_us", AccessTier.OFFICIAL_API, SourceStatus.BLOCKED,
                     U, U, U, Y, "NOT_A_LEADER_SOURCE"),
    SourceCapability("kalshi_public_trades", "kalshi", AccessTier.OFFICIAL_API, SourceStatus.PLANNED,
                     N, Y, U, N, "FOLLOWER_VENUE_ONLY"),
    SourceCapability("bitcoin_chain", "bitcoin", AccessTier.PERMITTED_PUBLIC_ENDPOINT, SourceStatus.PLANNED,
                     Y, Y, U, U, "NOT_A_LEADER_SOURCE"),
    SourceCapability("solana_evm_dex", "solana_evm_dex", AccessTier.PERMITTED_PUBLIC_ENDPOINT, SourceStatus.BLOCKED,
                     Y, U, Y, Y, "CANDIDATE_LATER"),
    SourceCapability("hyperliquid_ws", "hyperliquid", AccessTier.OFFICIAL_API, SourceStatus.BLOCKED,
                     U, Y, U, U, "CANDIDATE_LATER"),
)}


def first_source() -> SourceCapability:
    (first,) = [c for c in MATRIX.values() if c.research_verdict == "FIRST_SOURCE"]
    return first


class ResearchEligibility(str, Enum):
    RESEARCH_ALLOWED_ON_FIXTURES = "RESEARCH_ALLOWED_ON_FIXTURES"
    NOT_A_LEADER_SOURCE = "NOT_A_LEADER_SOURCE"


class ExecutionEligibility(str, Enum):
    BLOCKED_UNSUPPORTED = "BLOCKED_UNSUPPORTED"  # no permitted execution venue, product or grant


@dataclass(frozen=True)
class EligibilityAnswer:
    research: ResearchEligibility
    execution: ExecutionEligibility
    reasons: tuple[str, ...]


def eligibility(source_id: str, *, venue_eligibility_known: bool = False) -> EligibilityAnswer:
    """Research and execution answered separately. Execution is blocked for every source today."""
    cap = MATRIX[source_id]
    research = (ResearchEligibility.RESEARCH_ALLOWED_ON_FIXTURES if cap.research_verdict in ("FIRST_SOURCE",
                                                                                          "CANDIDATE_LATER")
                else ResearchEligibility.NOT_A_LEADER_SOURCE)
    reasons = ["no execution venue, product eligibility or automated grant is approved"]
    if not venue_eligibility_known:
        reasons.append("venue/product eligibility for our jurisdiction is not established")
    if cap.product == "polymarket_international":
        reasons.append("Polymarket international lists the US as close-only; Polymarket US is a separate product")
    return EligibilityAnswer(research, ExecutionEligibility.BLOCKED_UNSUPPORTED, tuple(reasons))
