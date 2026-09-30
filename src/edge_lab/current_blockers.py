"""Current research blockers and contract-exception summaries (PR C, R1; 2026-09-30). Pure data.

The canonical, machine-readable register behind `docs/research/CURRENT_BLOCKERS_2026-09-30.md`.
The document holds the narrative and the sources; this module holds each item's status, resolver
and trigger so the Terminal shows the same facts. `tests/test_current_blockers.py` keeps the two
in step (every id and status in both).

Rules:
- A status is a recorded state, never an outcome guess. UNKNOWN stays UNKNOWN.
- The register grants nothing. An item whose resolver is OWNER needs the owner's own decision.
- `reviewed_at_utc` is when the item was last reconciled. Past `REVIEW_MAX_AGE` it is STALE and the
  Terminal says so; stale is not current.
- Contract exceptions summarize how a sports contract's *payoff* can differ from the sporting
  result (tie, fallback price, shootout). They are summaries of recorded rules evidence, not rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from .freshness import parse_utc

REGISTER_VERSION = "current-blockers-v1"
REVIEW_MAX_AGE = timedelta(days=14)


class Status(str, Enum):
    FEE_UNSUPPORTED = "FEE_UNSUPPORTED"  # no verified fee: after-cost figures blocked, never 0
    RULES_UNRESOLVED = "RULES_UNRESOLVED"  # the payoff in a case is not stated anywhere read
    UNRESOLVED = "UNRESOLVED"  # an open question with no answer yet
    CORRECTION_PENDING = "CORRECTION_PENDING"  # a known wording error, corrected in the next version
    RECORDED = "RECORDED"  # a measured difference, kept as data; no action needed now
    NOT_SENT = "NOT_SENT"  # a drafted message waiting for the owner
    WAITING_FOR_WINDOW = "WAITING_FOR_WINDOW"  # blocked by a date, not by work
    OWNER_DECISION = "OWNER_DECISION"  # options prepared; the owner picks


class Resolver(str, Enum):
    OWNER = "OWNER"
    AGENT = "AGENT"
    VENUE = "VENUE"  # an answer or a published document from the venue


@dataclass(frozen=True)
class Blocker:
    blocker_id: str
    title: str
    scope: str
    status: Status
    verified: str
    unknown: str
    resolver: Resolver
    resolver_detail: str
    trigger: str
    sources: tuple[str, ...]
    owner_approval_needed: bool
    due_utc: str | None = None  # the date the trigger is expected, when one is known
    reviewed_at_utc: str = "2026-09-30T09:40:00+00:00"


@dataclass(frozen=True)
class ContractException:  # a summary of recorded rules evidence, not a rule
    case: str
    status: str  # VERIFIED / RULES_UNRESOLVED / OBSERVED
    summary: str
    source: str


BLOCKERS: tuple[Blocker, ...] = (
    Blocker("ROUTINE_OFFHOST_BACKUP", "Weekly off-host pull (O1) and F09", "Operations", Status.WAITING_FOR_WINDOW,
            "A retention apply refuses after 8 days without F09 (HANDOFF 2026-09-29).",
            "Nothing; the owner runs the routine.", Resolver.OWNER, "the owner's laptop routine",
            "by about 2026-10-03", ("HANDOFF.md (UNRESOLVED: Routine)",), True, "2026-10-03T12:00:00+00:00"),
    Blocker("KALSHI_MESSAGE_REV2", "Kalshi support message, revision 2", "Venue facts", Status.NOT_SENT,
            "Revision 2 is drafted (fees Q7, data terms Q10 and more); revision 1 was shown on 2026-09-26.",
            "Kalshi's answers.", Resolver.OWNER, "the owner confirms the text and sends it; agents never send",
            "owner confirmation", ("docs/research/KALSHI_QUESTIONS_2026-09-26.md",
                                   "docs/owner/2026-09-29-vf-decision-packet.md §A"), True),
    Blocker("FEE_KXNFLGAME", "KXNFLGAME fees", "EXP-002 (NFL)", Status.FEE_UNSUPPORTED,
            "KXNFLGAME is on the captured non-standard fee list (PDF pp.6-11); no verification record exists. "
            "The public Fees help page (read 2026-09-30) defers per-series fees to the fee-schedule PDF.",
            "The series' multiplier and maker-fee semantics.", Resolver.VENUE,
            "a Kalshi answer (message Q7) or a primary document; the fee owner then adds a verification record",
            "a Kalshi reply or a new fee-schedule PDF", ("docs/research/EXP002_FEE_VERIFICATION.md",
                                                         "tests/test_fee_kxnflgame_unverified.py"), False),
    Blocker("FEE_KXNHLGAME", "KXNHLGAME fees", "NHL (development only)", Status.FEE_UNSUPPORTED,
            "Routing now matches KXNFLGAME: KXNHLGAME extends the listed KXNHL family, so fee_schedules returns "
            "FEE_UNSUPPORTED instead of the general schedule (this PR). The series metadata reads "
            "quadratic_with_maker_fees, multiplier 1 (ADR 0040); no primary document verifies it.",
            "Whether the general quadratic schedule applies.", Resolver.VENUE,
            "a Kalshi answer or a primary document, then a verification record",
            "a Kalshi reply or a new fee-schedule PDF", ("docs/decisions/0040-kalshi-nhl-prospective-evidence.md",
                                                         "tests/test_fee_family_routing.py"), False),
    Blocker("FEE_KXMVE_COMBOS", "Combination (KXMVE*) fees", "RFQ research (R4)", Status.FEE_UNSUPPORTED,
            "KXMVE is on the captured non-standard list; combination series such as KXMVECROSSCATEGORY extend "
            "it and now route to FEE_UNSUPPORTED by prefix (this PR).",
            "Combination-market fee semantics, including RFQ target-cost modes.", Resolver.VENUE,
            "a primary document; the RFQ feasibility packet (#148) records the RFQ side",
            "#148 merged, or a Kalshi document", ("tests/test_fee_family_routing.py",), False),
    Blocker("NFL_FALLBACK_WORDING", "EXP-002 freeze proposal §2 fallback wording", "EXP-002 (NFL)",
            Status.CORRECTION_PENDING,
            "The terms' Venue Change clause triggers the fair-price fallback only when the game moves outside "
            "the scheduling week or the home/away designation is reversed; v1 §2 says 'a venue or home/away "
            "change', which is broader.",
            "Nothing about the rule; only the proposal's wording.", Resolver.AGENT,
            "the freeze-review packet author corrects it in freeze proposal v2",
            "freeze proposal v2, before the 2026-10-22 review",
            ("docs/research/EXP002_TIE_NOTPLAYED_BOUNDS.md §1", "docs/research/EXP002_FREEZE_PROPOSAL.md §2"), False,
            "2026-10-22T04:00:00+00:00"),
    Blocker("NHL_SHOOTOUT_TIE", "KXNHLGAME shootout and tie payout", "NHL (development only)",
            Status.RULES_UNRESOLVED,
            "Overtime is included (contract terms); postponement and cancellation are stated in the market rules.",
            "Whether a shootout winner resolves Yes, and how a tie pays.", Resolver.VENUE,
            "a Kalshi answer; not in message revision 2, so adding it needs the owner",
            "only before a hockey experiment needs it", ("docs/decisions/0040-kalshi-nhl-prospective-evidence.md",
                                                         "docs/owner/2026-09-29-nhl-decision-packet.md"), False),
    Blocker("DATA_RIGHTS", "Kalshi data rights (Data Terms vs Developer Agreement)", "All Kalshi data",
            Status.UNRESOLVED,
            "The Data Terms PDF was read and hashed; it is written about website content.",
            "Which terms govern API-collected data, and whether private storage and research use are covered.",
            Resolver.OWNER, "the owner reads the Developer Agreement and decides (message Q10 may help)",
            "owner decision", ("docs/research/INPLAY_SOURCE_FEASIBILITY.md §1.9",
                               "docs/owner/2026-09-29-vf-decision-packet.md"), True),
    Blocker("NHL_ODDS_COMMENCE_OFFSET", "Odds API NHL commence times", "NHL (development only)", Status.RECORDED,
            "The Odds API lists NHL commence times about 10 minutes after NHL.com's, so its T-60m is about T-50m "
            "of the official start. Provider data is not altered.",
            "Whether the offset is constant.", Resolver.AGENT,
            "a future hockey protocol states which start time it uses", "a hockey experiment proposal",
            ("HANDOFF.md (UNRESOLVED: NHL)",), False),
    Blocker("NHL_READ_TIME_GAP", "NHL T-60m reads 60 min apart for 19:00 ET games", "NHL (development only)",
            Status.OWNER_DECISION,
            "Protected windows move the Odds read to 18:35 ET (T-25m) and the Kalshi read to 17:35 ET (T-85m) for "
            "19:00 ET games, about 36% of NHL games. Both reads record their real lead.",
            "Nothing; it is a choice.", Resolver.OWNER, "packet decision 2: (a) leave as is (default) or (b) one "
            "shared protected-window contract", "owner decision",
            ("docs/owner/2026-09-29-nhl-decision-packet.md, decision 2",), True),
    Blocker("EXP002_AC_TIMING_RUN", "EXP-002 A.C timing calibration run", "EXP-002 (NFL)",
            Status.WAITING_FOR_WINDOW, "The tool is built and deployed (#142, #143).",
            "Its result.", Resolver.AGENT, "one logged run on production after the pilot weeks; never early",
            "after about 2026-10-19", ("docs/research/EXP002_AC_CALIBRATION_TOOL.md",), False,
            "2026-10-19T12:00:00+00:00"),
    Blocker("EXP002_FREEZE_REVIEW", "EXP-002 owner freeze review", "EXP-002 (NFL)", Status.OWNER_DECISION,
            "Sourced tie and not-played bounds are PROPOSED (#138); E1 design review and fees remain open.",
            "The freeze outcome; no freeze is promised.", Resolver.OWNER, "the owner, with evidence, fees and rules",
            "2026-10-22", ("docs/research/EXP002_FREEZE_PROPOSAL.md", "HANDOFF.md"), True,
            "2026-10-22T04:00:00+00:00"),
)

OPEN_STATUSES = frozenset(set(Status) - {Status.RECORDED})


CONTRACT_EXCEPTIONS: dict[str, tuple[ContractException, ...]] = {
    "KXNFLGAME": (
        ContractException("Tie after overtime", "VERIFIED", "Pays $1 divided by the tied teams, rounded down: $0.50.",
                   "FOOTBALLGAMEWIN contract terms (EXP002_TIE_NOTPLAYED_BOUNDS §1)"),
        ContractException("Fair-price fallback", "VERIFIED",
                   "A discretionary last fair price F in [0, 1] if the game is not started within 48 h, suspended "
                   "before 55 min and not resumed, forfeited, moved outside its week or home/away-reversed, or hit "
                   "by a pre-game disqualification.", "FOOTBALLGAMEWIN contract terms, Venue Change clause"),
        ContractException("Venue change, same designation", "VERIFIED",
                   "Resolves normally when the game is played within 48 h with home/away unchanged.",
                   "FOOTBALLGAMEWIN contract terms"),
        ContractException("Observed settlements", "OBSERVED",
                   "The 2025 GB–DAL tie settled at 0.50; no fallback-F settlement has been observed.",
                   "#138"),
    ),
    "KXNHLGAME": (
        ContractException("Overtime", "VERIFIED", "Included: the default period is regulation plus overtime.",
                   "HOCKEYWINNINGINPERIOD contract terms (ADR 0040)"),
        ContractException("Shootout", "RULES_UNRESOLVED",
                   "Not mentioned; a shootout winner resolving Yes is the likely reading, not a stated rule.",
                   "ADR 0040"),
        ContractException("Tie", "RULES_UNRESOLVED", "No tie payout is stated; a drawn team 'may' resolve No.", "ADR 0040"),
        ContractException("Postponed or cancelled", "VERIFIED",
                   "Not started within 48 h of the scheduled date: fair-price fallback.", "market rules text (ADR 0040)"),
    ),
}


def series_of(native_id: str | None) -> str | None:
    if not native_id:
        return None
    return native_id.split("-", 1)[0].upper()


def exceptions_for(native_id: str | None) -> tuple[ContractException, ...] | None:
    """The contract-exception summary for a market's series, or None when none is recorded."""
    return CONTRACT_EXCEPTIONS.get(series_of(native_id) or "")


def is_stale(blocker: Blocker, now: datetime) -> bool:
    reviewed = parse_utc(blocker.reviewed_at_utc)
    return reviewed is None or now - reviewed > REVIEW_MAX_AGE


def open_blockers(blockers: tuple[Blocker, ...] | None = None) -> list[Blocker]:
    return [b for b in (BLOCKERS if blockers is None else blockers) if b.status in OPEN_STATUSES]


def next_blocker(now: datetime, blockers: tuple[Blocker, ...] | None = None) -> Blocker | None:
    """The next open item: the soonest one with a due date still ahead (or overdue), else the first
    owner-approval item, else the first open item. None when nothing is open."""
    items = open_blockers(blockers)
    if not items:
        return None
    dated = [(parse_utc(b.due_utc), b) for b in items if b.due_utc]
    if dated:
        return min(dated, key=lambda x: x[0])[1]
    owner = [b for b in items if b.owner_approval_needed]
    return (owner or items)[0]


def validate(blockers: tuple[Blocker, ...] | None = None) -> list[str]:
    """Every problem with the register; empty when it is consistent."""
    blockers = BLOCKERS if blockers is None else blockers
    out = []
    ids = [b.blocker_id for b in blockers]
    if len(ids) != len(set(ids)):
        out.append("duplicate blocker ids")
    for b in blockers:
        if not isinstance(b.status, Status) or not isinstance(b.resolver, Resolver):
            out.append(f"{b.blocker_id}: status or resolver outside the vocabulary")
        if not b.sources:
            out.append(f"{b.blocker_id}: no source")
        if parse_utc(b.reviewed_at_utc) is None or (b.due_utc is not None and parse_utc(b.due_utc) is None):
            out.append(f"{b.blocker_id}: a time is not timezone-aware")
    return out
