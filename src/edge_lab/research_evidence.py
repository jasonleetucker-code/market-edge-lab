"""Research-evidence lineage: evidence consumption and attrition (Economic Evidence v1, #96).

The canonical owner of two research-governance contracts that sit beside the experiment
registry (`edge_lab.experiments`). It is not a second registry, ledger or AI-memory store:
each experiment's consumption log lives in its own registry directory, and attrition is a
pure report over units the caller enumerates from existing stores.

**1. Evidence consumption** (`EvidenceUse`, `record_use`, `holdout_status`).
Who used which dataset, in which role and window, how, and whether features, labels or
results were seen or influenced tuning. Rules:
- the log (`experiments/<EXP>/evidence_use.jsonl`) is append-only. `check_append_only`
  compares it with a git base; CI runs it through `edge-lab experiments check-frozen`;
- an event id is the hash of the event's content. Re-recording an identical event is a no-op.
  Every distinct view is a new event; nothing else is deduplicated;
- a holdout is identified by its outcome/event **window** (scope plus interval) as well as by
  its dataset hash. Copying, renaming or re-hashing the same outcomes never makes them
  untouched again;
- access history from before a log existed is UNKNOWN (`UNKNOWN_LEGACY`), never certified
  untouched. So is any scope that no log declares it covers (`covered_scopes`), and any scope
  with a known consumer that does not log (`KNOWN_UNLOGGED_CONSUMERS`: EXP-001's pipeline,
  ledger and Terminal read KXHIGHNY outcomes daily). Unknown booleans (None) count as the
  worst case. Scopes are compared case-insensitively;
- a protocol's `prohibited_inputs` (dataset-id prefixes) and `prohibited_label_scopes`
  (outcome scopes whose labels or results it may never view) are refused at record time.
  Family B never logs access to EXP-001 forecasts, outcomes or ledger, nor to KXHIGHNY labels
  through any dataset.
- **Limitation, stated in every status:** a log records declared access. It cannot prove that
  nobody viewed a file outside it. Holdout protection stays procedural as well as technical.

**2. Attrition** (`AttritionUnit`, `attrition_report`).
Separate denominators for events, markets, scheduled horizons, snapshots and opportunities;
every raw reason kept; one deterministic primary reason per unit (the `Exclusion` order),
so the waterfall reconciles without double counting. Zero is not missing (a level not
enumerated is None). No signal is not a failed collection, and no fill is not "no
opportunity". A scheduled target whose deadline has not passed is PENDING_TARGET, never
MISSED.

Pure, deterministic, stdlib-only and network-free. EXP-001 reporting is not touched.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .freshness import parse_utc
from .provenance import canonical_json, sha256_hex

LOG_NAME = "evidence_use.jsonl"
LOG_VERSION = "evidence-use-v1"
ATTRITION_VERSION = "attrition-v1"
OUT_OF_BAND_LIMITATION = (
    "An evidence-use log records declared access only. It cannot prove that nobody viewed the data "
    "outside it (another tool, a copy, a shell, a chat), and scopes, roles and viewed flags are self-declared: "
    "a mislabelled scope or flag sidesteps the checks. Holdout protection is procedural as well as technical."
)


# Scopes whose outcomes are read by processes that keep no evidence-use log. A window in such a
# scope can never be certified untouched (review SF-5).
KNOWN_UNLOGGED_CONSUMERS: dict[str, str] = {
    "kalshi:kxhighny": "EXP-001's daily pipeline, shadow ledger, settlement runs and Terminal read KXHIGHNY "
                       "outcomes without an evidence-use log",
}


def norm_scope(scope: str) -> str:
    return scope.strip().lower()


def scope_matches(scope: str, prefix: str) -> bool:
    """True when `scope` is `prefix` or lies under it (':'-separated, case-insensitive)."""
    s, p = norm_scope(scope), norm_scope(prefix)
    return bool(p) and (s == p or s.startswith(p + ":") or s.startswith(p + "-"))


class EvidenceError(ValueError):
    """An evidence-use event or log is malformed, conflicting or not allowed."""


class ProhibitedInput(EvidenceError):
    """The experiment's protocol forbids access to this dataset."""


# --------------------------------------------------------------------------- consumption


class DatasetRole(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"  # training / development data
    VALIDATION = "VALIDATION"  # model or rule selection
    HOLDOUT = "HOLDOUT"  # reserved for the single preregistered evaluation
    OPERATIONAL = "OPERATIONAL"  # collected or served by operations, not by research
    UNASSIGNED = "UNASSIGNED"


class Action(str, Enum):
    UNTOUCHED_EVALUATION = "UNTOUCHED_EVALUATION"  # the preregistered evaluation of a holdout
    OPERATIONAL_ACCESS = "OPERATIONAL_ACCESS"  # a collector, backup or supervisor touched it
    FEATURE_INSPECTION = "FEATURE_INSPECTION"  # inputs viewed, labels and results not
    LABEL_RESULT_INSPECTION = "LABEL_RESULT_INSPECTION"  # outcomes, labels or results viewed
    VALIDATION_TUNING = "VALIDATION_TUNING"  # used to choose or tune anything
    TRAINING_DEVELOPMENT = "TRAINING_DEVELOPMENT"  # used to build anything


class HoldoutState(str, Enum):
    """Best to worst for an untouched-evaluation claim."""

    UNTOUCHED = "UNTOUCHED"
    FEATURES_VIEWED = "FEATURES_VIEWED"  # inputs seen; labels/results not; not "untouched"
    UNKNOWN_LEGACY = "UNKNOWN_LEGACY"  # outcomes existed before the log: history unknown
    CONSUMED = "CONSUMED"  # already evaluated once; a second look is validation, not a test
    CONTAMINATED = "CONTAMINATED"  # labels/results viewed, tuned on or developed on


_STATE_ORDER = {s: i for i, s in enumerate(HoldoutState)}


@dataclass(frozen=True)
class InformationWindow:
    """The outcomes a dataset carries: a scope (outcome universe) and an interval of event times.

    `scope` names the universe, for example "sports:nfl:moneyline" or "kalshi:KXHIGHNY".
    Two windows in one scope that overlap in time carry some of the same outcomes, whatever
    their dataset ids or hashes."""

    scope: str
    start_utc: str
    end_utc: str

    def bounds(self) -> tuple[datetime, datetime]:
        start, end = parse_utc(self.start_utc), parse_utc(self.end_utc)
        if start is None or end is None:
            raise EvidenceError(f"window {self.start_utc}..{self.end_utc} needs timezone-aware UTC times")
        if end < start:
            raise EvidenceError(f"window ends before it starts: {self.start_utc}..{self.end_utc}")
        return start, end

    def overlaps(self, other: "InformationWindow") -> bool:
        if norm_scope(self.scope) != norm_scope(other.scope):
            return False
        a0, a1 = self.bounds()
        b0, b1 = other.bounds()
        return a0 <= b1 and b0 <= a1


@dataclass(frozen=True)
class EvidenceUse:
    """One declared use of one dataset. Unknown booleans stay None (and count as the worst case)."""

    experiment_id: str
    family: str
    dataset_id: str  # "<namespace>:<name>", e.g. "the_odds_api:nfl_h2h" or "exp001:gate3_dataset"
    dataset_version: str
    dataset_sha256: str
    role: DatasetRole
    window: InformationWindow
    actor: str  # who: "owner", "claude-code:<session>", a service name
    tool: str  # how: a CLI command, a script, a notebook, a UI view
    action_time_utc: str
    action: Action
    code_version: str  # git commit of the code that ran
    model_version: str | None  # LLM model id when an LLM saw the data, else None
    prompt_version: str | None  # prompt hash/version when an LLM saw the data, else None
    viewed_features: bool | None
    viewed_labels: bool | None
    viewed_results: bool | None
    influenced_tuning: bool | None
    note: str = ""
    sequence: int = 0  # distinguishes two otherwise identical views (same second, same actor)

    def content(self) -> dict[str, Any]:
        data = asdict(self)
        data["role"] = self.role.value
        data["action"] = self.action.value
        return data

    @property
    def event_id(self) -> str:
        return "eu-" + sha256_hex(canonical_json(self.content()))[:32]

    def to_dict(self) -> dict[str, Any]:
        return {"record": "use", "event_id": self.event_id, **self.content()}

    def validate(self) -> None:
        for name in ("experiment_id", "family", "dataset_id", "dataset_version", "dataset_sha256", "actor", "tool",
                     "code_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise EvidenceError(f"evidence use needs a non-empty {name}")
        if not isinstance(self.role, DatasetRole) or not isinstance(self.action, Action):
            raise EvidenceError("role and action must be DatasetRole / Action members")
        if parse_utc(self.action_time_utc) is None:
            raise EvidenceError(f"action_time_utc {self.action_time_utc!r} is not a timezone-aware time")
        self.window.bounds()
        for name in ("viewed_features", "viewed_labels", "viewed_results", "influenced_tuning"):
            if getattr(self, name) not in (True, False, None):
                raise EvidenceError(f"{name} must be true, false or null (unknown)")
        if self.action is Action.UNTOUCHED_EVALUATION and self.role is not DatasetRole.HOLDOUT:
            raise EvidenceError("an UNTOUCHED_EVALUATION uses a HOLDOUT dataset")
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 0:
            raise EvidenceError("sequence must be a non-negative integer")


def use_from_dict(data: Mapping[str, Any]) -> EvidenceUse:
    try:
        window = data["window"]
        use = EvidenceUse(
            experiment_id=data["experiment_id"], family=data["family"], dataset_id=data["dataset_id"],
            dataset_version=data["dataset_version"], dataset_sha256=data["dataset_sha256"],
            role=DatasetRole(data["role"]),
            window=InformationWindow(window["scope"], window["start_utc"], window["end_utc"]),
            actor=data["actor"], tool=data["tool"], action_time_utc=data["action_time_utc"],
            action=Action(data["action"]), code_version=data["code_version"],
            model_version=data.get("model_version"), prompt_version=data.get("prompt_version"),
            viewed_features=data.get("viewed_features"), viewed_labels=data.get("viewed_labels"),
            viewed_results=data.get("viewed_results"), influenced_tuning=data.get("influenced_tuning"),
            note=data.get("note", ""), sequence=data.get("sequence", 0),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EvidenceError(f"malformed evidence-use record: {exc}") from None
    return use


@dataclass(frozen=True)
class EvidenceLog:
    path: Path | None
    experiment_id: str | None
    started_at_utc: str | None  # None: no log, so all history is UNKNOWN
    uses: tuple[EvidenceUse, ...]
    covered_scopes: tuple[str, ...] = ()  # the outcome scopes whose research access this log records


def read_log(path: Path) -> EvidenceLog:
    """Parse and verify one log. A missing file is an empty log with an unknown start."""
    if not path.exists():
        return EvidenceLog(path, None, None, (), ())
    header: dict[str, Any] | None = None
    uses: list[EvidenceUse] = []
    seen: dict[str, EvidenceUse] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            raise EvidenceError(f"{path}:{number}: not JSON: {exc}") from None
        if record.get("record") == "header":
            if header is not None or uses:
                raise EvidenceError(f"{path}:{number}: the header must be the first and only header line")
            if record.get("log_version") != LOG_VERSION or parse_utc(record.get("started_at_utc")) is None:
                raise EvidenceError(f"{path}:{number}: header needs log_version {LOG_VERSION} and started_at_utc")
            header = record
            continue
        if record.get("record") != "use":
            raise EvidenceError(f"{path}:{number}: unknown record kind {record.get('record')!r}")
        use = use_from_dict(record)
        if record.get("event_id") != use.event_id:
            raise EvidenceError(f"{path}:{number}: event_id does not match the event's content (edited?)")
        if use.event_id in seen:
            raise EvidenceError(f"{path}:{number}: duplicate event {use.event_id}")
        seen[use.event_id] = use
        uses.append(use)
    if header is None:
        raise EvidenceError(f"{path}: missing header line")
    scopes = header.get("covered_scopes", [])
    if not isinstance(scopes, list) or not all(isinstance(s, str) and s.strip() for s in scopes):
        raise EvidenceError(f"{path}: covered_scopes must be a list of non-empty strings")
    return EvidenceLog(path, header.get("experiment_id"), header["started_at_utc"], tuple(uses), tuple(scopes))


def init_log(path: Path, *, experiment_id: str, started_at_utc: str, covered_scopes: Sequence[str] = ()) -> Path:
    """Create an empty log with its header. Refuses to overwrite: history is never restarted.

    `covered_scopes` declares the outcome scopes whose research access this log records. A
    scope no log covers stays UNKNOWN for holdout purposes."""
    if path.exists():
        raise EvidenceError(f"{path} already exists; an evidence log is never restarted")
    if parse_utc(started_at_utc) is None:
        raise EvidenceError("started_at_utc must be a timezone-aware time")
    header = {"record": "header", "log_version": LOG_VERSION, "experiment_id": experiment_id,
              "started_at_utc": started_at_utc, "covered_scopes": [norm_scope(s) for s in covered_scopes],
              "limitation": OUT_OF_BAND_LIMITATION}
    path.write_text(canonical_json(header) + "\n", encoding="utf-8", newline="\n")
    return path


def is_prohibited(dataset_id: str, prohibited_prefixes: Sequence[str]) -> str | None:
    for prefix in prohibited_prefixes:
        if prefix and dataset_id.startswith(prefix):
            return prefix
    return None


def record_use(path: Path, use: EvidenceUse, *, prohibited_prefixes: Sequence[str] = (),
               prohibited_label_scopes: Sequence[str] = ()) -> str:
    """Append one event. Returns "APPENDED" or "DUPLICATE" (an identical event already logged).

    Raises ProhibitedInput when the experiment's protocol forbids the dataset, or forbids
    viewing labels/results in the event's outcome scope (whatever the dataset is called), and
    EvidenceError when the event is malformed or the log is missing or invalid."""
    use.validate()
    blocked = is_prohibited(use.dataset_id, prohibited_prefixes)
    if blocked:
        raise ProhibitedInput(f"{use.experiment_id} may not access {use.dataset_id} (prohibited_inputs {blocked!r})")
    for scope in prohibited_label_scopes:
        # Outcome-derived results count as labels here: tuning or development that saw results in
        # the scope is refused too.
        if scope_matches(use.window.scope, scope) and (
                use.viewed_labels is not False or use.action is Action.LABEL_RESULT_INSPECTION
                or (use.action in (Action.VALIDATION_TUNING, Action.TRAINING_DEVELOPMENT)
                    and use.viewed_results is not False)):
            raise ProhibitedInput(f"{use.experiment_id} may not view labels or outcomes in scope {use.window.scope} "
                                  f"(prohibited_label_scopes {scope!r}); viewed_labels must be false")
    if not path.exists():
        raise EvidenceError(f"{path} does not exist; create it with init_log first")
    log = read_log(path)
    if log.experiment_id != use.experiment_id:
        raise EvidenceError(f"{path} belongs to {log.experiment_id}, not {use.experiment_id}")
    if any(u.event_id == use.event_id for u in log.uses):
        return "DUPLICATE"
    text = path.read_text(encoding="utf-8")
    prefix = "" if text.endswith("\n") else "\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(prefix + canonical_json(use.to_dict()) + "\n")
    return "APPENDED"


def load_all_logs(experiments_root: Path) -> list[EvidenceLog]:
    """Every experiment's log. Consumption is judged across experiments: another family viewing
    the same outcomes consumes them too."""
    return [read_log(p) for p in sorted(experiments_root.glob(f"*/{LOG_NAME}"))]


@dataclass(frozen=True)
class HoldoutStatus:
    state: HoldoutState
    clean_untouched_claim_allowed: bool
    matching_event_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    limitation: str = OUT_OF_BAND_LIMITATION

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state.value, "clean_untouched_claim_allowed": self.clean_untouched_claim_allowed,
                "matching_event_ids": list(self.matching_event_ids), "reasons": list(self.reasons),
                "limitation": self.limitation}


def _use_state(use: EvidenceUse) -> tuple[HoldoutState, str]:
    unknown = [n for n in ("viewed_labels", "viewed_results", "influenced_tuning") if getattr(use, n) is None]
    if use.action in (Action.LABEL_RESULT_INSPECTION, Action.VALIDATION_TUNING, Action.TRAINING_DEVELOPMENT):
        return HoldoutState.CONTAMINATED, f"{use.event_id}: {use.action.value}"
    if use.viewed_labels or use.viewed_results or use.influenced_tuning:
        if use.action is Action.UNTOUCHED_EVALUATION and use.influenced_tuning is False:
            return HoldoutState.CONSUMED, f"{use.event_id}: evaluated once already ({use.action_time_utc})"
        return HoldoutState.CONTAMINATED, f"{use.event_id}: labels/results viewed or tuning influenced"
    if unknown:
        return HoldoutState.CONTAMINATED, f"{use.event_id}: {', '.join(unknown)} UNKNOWN (counted as viewed)"
    if use.action is Action.UNTOUCHED_EVALUATION:
        return HoldoutState.CONSUMED, f"{use.event_id}: evaluated once already ({use.action_time_utc})"
    if use.viewed_features is not False:
        return HoldoutState.FEATURES_VIEWED, f"{use.event_id}: features viewed" + (
            " (UNKNOWN, counted as viewed)" if use.viewed_features is None else "")
    return HoldoutState.UNTOUCHED, f"{use.event_id}: {use.action.value} without viewing features, labels or results"


def holdout_status(logs: Iterable[EvidenceLog], *, dataset_sha256: str, window: InformationWindow) -> HoldoutStatus:
    """Can this dataset/window still support a clean untouched-evaluation claim?

    Matching is by dataset hash **or** by an overlapping outcome window in the same scope
    (case-insensitive), across every experiment's log. UNKNOWN_LEGACY at best when:
    - no log declares that it covers the scope;
    - the scope has a known unlogged consumer;
    - the outcomes predate the earliest covering log.

    Only UNTOUCHED allows a clean claim."""
    start, _ = window.bounds()
    logs = list(logs)
    covering = [log for log in logs if log.started_at_utc
                and any(scope_matches(window.scope, s) for s in log.covered_scopes)]
    starts = [parse_utc(log.started_at_utc) for log in covering]
    reasons: list[str] = []
    state = HoldoutState.UNTOUCHED
    if not starts:
        state, reasons = HoldoutState.UNKNOWN_LEGACY, [
            f"no evidence-use log covers scope {norm_scope(window.scope)!r}: access history is UNKNOWN"]
    elif start < min(starts):
        state = HoldoutState.UNKNOWN_LEGACY
        reasons.append(f"outcomes from {window.start_utc} predate the first covering evidence log "
                       f"({min(starts).isoformat()}): earlier access is UNKNOWN")
    for prefix, consumer in KNOWN_UNLOGGED_CONSUMERS.items():
        if scope_matches(window.scope, prefix):
            state = max(state, HoldoutState.UNKNOWN_LEGACY, key=_STATE_ORDER.__getitem__)
            reasons.append(f"known unlogged consumer of {prefix}: {consumer}")
    matches: list[str] = []
    for log in logs:
        for use in log.uses:
            if use.dataset_sha256 != dataset_sha256 and not use.window.overlaps(window):
                continue
            matches.append(use.event_id)
            use_state, why = _use_state(use)
            if use_state is not HoldoutState.UNTOUCHED:
                reasons.append(why)
            if _STATE_ORDER[use_state] > _STATE_ORDER[state]:
                state = use_state
    return HoldoutStatus(state, state is HoldoutState.UNTOUCHED, tuple(sorted(matches)), tuple(reasons))


def check_append_only(base_ref: str, *, repo: Path) -> list[str]:
    """Evidence logs modified other than by appending, or deleted, relative to `base_ref`."""
    out = subprocess.run(
        ["git", "diff", "--name-status", base_ref, "HEAD", "--", f"experiments/*/{LOG_NAME}"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout
    problems: list[str] = []
    for line in out.splitlines():
        if not line or line.startswith("A"):
            continue
        status, _, path = line.partition("\t")
        if not status.startswith("M"):
            problems.append(f"{line} (an evidence-use log may only be appended to)")
            continue
        before = subprocess.run(["git", "show", f"{base_ref}:{path}"], cwd=repo, capture_output=True, text=True,
                                check=True).stdout.replace("\r\n", "\n")
        after = subprocess.run(["git", "show", f"HEAD:{path}"], cwd=repo, capture_output=True, text=True,
                               check=True).stdout.replace("\r\n", "\n")
        if not after.startswith(before):
            problems.append(f"{line} (existing lines changed; an evidence-use log may only be appended to)")
    return problems


# --------------------------------------------------------------------------- attrition


class Level(str, Enum):
    """Separate denominators. Units of different levels are never pooled."""

    EVENT = "EVENT"
    MARKET = "MARKET"
    HORIZON = "HORIZON"  # a scheduled capture target (market x offset)
    SNAPSHOT = "SNAPSHOT"
    OPPORTUNITY = "OPPORTUNITY"


class Stage(str, Enum):
    AVAILABILITY = "AVAILABILITY"
    FRESHNESS = "FRESHNESS"
    SEMANTICS = "SEMANTICS"
    LIQUIDITY = "LIQUIDITY"
    CAPITAL = "CAPITAL"
    SIGNAL = "SIGNAL"
    FILL = "FILL"
    OUTCOME = "OUTCOME"


class Exclusion(str, Enum):
    """Primary-reason precedence is this declaration order (earliest stage first)."""

    PENDING_TARGET = "PENDING_TARGET"  # deadline not passed: never MISSED
    COLLECTION_FAILURE = "COLLECTION_FAILURE"  # an attempt ran and failed
    MISSED_TARGET = "MISSED_TARGET"  # deadline passed with no capture
    MISSING_SOURCE = "MISSING_SOURCE"  # the source has nothing for it (not listed, no book)
    PARTIAL_EVIDENCE = "PARTIAL_EVIDENCE"  # some required inputs missing
    STALE = "STALE"  # inputs too old at the cutoff, or UNKNOWN freshness
    RULES_UNRESOLVED = "RULES_UNRESOLVED"  # rules not captured or not mapped
    UNSUPPORTED_PAYOFF = "UNSUPPORTED_PAYOFF"  # payoff or states outside the supported set
    DEPTH_UNKNOWN = "DEPTH_UNKNOWN"  # truncated capture ran out
    INSUFFICIENT_DEPTH = "INSUFFICIENT_DEPTH"  # complete capture offers too little
    CAPITAL_VETO = "CAPITAL_VETO"  # capital, risk or starter-policy veto
    NO_SIGNAL = "NO_SIGNAL"  # eligible, but the rule did not fire
    NO_FILL = "NO_FILL"  # signal, but the fill model did not fill
    OUTCOME_PENDING = "OUTCOME_PENDING"  # not final yet
    OUTCOME_VOID = "OUTCOME_VOID"  # final, but void/refund/cancelled: not evaluable


STAGE_OF: dict[Exclusion, Stage] = {
    Exclusion.PENDING_TARGET: Stage.AVAILABILITY,
    Exclusion.COLLECTION_FAILURE: Stage.AVAILABILITY,
    Exclusion.MISSED_TARGET: Stage.AVAILABILITY,
    Exclusion.MISSING_SOURCE: Stage.AVAILABILITY,
    Exclusion.PARTIAL_EVIDENCE: Stage.AVAILABILITY,
    Exclusion.STALE: Stage.FRESHNESS,
    Exclusion.RULES_UNRESOLVED: Stage.SEMANTICS,
    Exclusion.UNSUPPORTED_PAYOFF: Stage.SEMANTICS,
    Exclusion.DEPTH_UNKNOWN: Stage.LIQUIDITY,
    Exclusion.INSUFFICIENT_DEPTH: Stage.LIQUIDITY,
    Exclusion.CAPITAL_VETO: Stage.CAPITAL,
    Exclusion.NO_SIGNAL: Stage.SIGNAL,
    Exclusion.NO_FILL: Stage.FILL,
    Exclusion.OUTCOME_PENDING: Stage.OUTCOME,
    Exclusion.OUTCOME_VOID: Stage.OUTCOME,
}
_PRECEDENCE = {e: i for i, e in enumerate(Exclusion)}
# A capture that has not happened yet is pending until its deadline, not missing or failed.
_PREMATURE = {Exclusion.COLLECTION_FAILURE, Exclusion.MISSED_TARGET, Exclusion.MISSING_SOURCE,
              Exclusion.PARTIAL_EVIDENCE}
_BEFORE_ELIGIBLE = {Stage.AVAILABILITY, Stage.FRESHNESS, Stage.SEMANTICS, Stage.LIQUIDITY, Stage.CAPITAL}


@dataclass(frozen=True)
class AttritionUnit:
    level: Level
    unit_id: str
    reasons: tuple[str, ...] = ()  # every raw reason (Exclusion values); empty = survived every stage
    deadline_utc: str | None = None  # a scheduled target's capture deadline, when it has one
    cluster_id: str | None = None  # game / event day, for clustered reporting


@dataclass(frozen=True)
class WaterfallRow:
    exclusion: str
    stage: str
    primary_count: int | None  # None: the stage is NOT_APPLICABLE to this protocol
    remaining_after: int


@dataclass(frozen=True)
class Waterfall:
    level: str
    start: int | None  # None: this level was not enumerated (unknown, not zero)
    rows: tuple[WaterfallRow, ...]
    survivors: int | None
    raw_reason_counts: dict[str, int]  # may sum to more than `start`: units carry several reasons
    corrected_premature: tuple[str, ...]  # units whose reasons were corrected against their deadline
    clusters: int | None  # distinct cluster ids among the units (None when not given)
    reconciled: bool


@dataclass(frozen=True)
class AttritionReport:
    version: str
    as_of_utc: str
    not_applicable_stages: tuple[str, ...]
    denominators: dict[str, int | None]
    waterfalls: tuple[Waterfall, ...]
    report_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return _plain(asdict(self))


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _primary(unit: AttritionUnit, as_of: datetime,
             not_applicable: set[Stage]) -> tuple[Exclusion | None, bool, tuple[str, ...]]:
    reasons: list[Exclusion] = []
    for raw in unit.reasons:
        try:
            reason = Exclusion(raw)
        except ValueError:
            raise ValueError(f"{unit.level.value} {unit.unit_id}: unknown attrition reason {raw!r}") from None
        if STAGE_OF[reason] in not_applicable:
            raise ValueError(f"{unit.level.value} {unit.unit_id}: reason {raw} belongs to a NOT_APPLICABLE stage")
        reasons.append(reason)
    corrected = False
    deadline = parse_utc(unit.deadline_utc) if unit.deadline_utc else None
    if unit.deadline_utc and deadline is None:
        raise ValueError(f"{unit.level.value} {unit.unit_id}: unparseable deadline {unit.deadline_utc!r}")
    if deadline is not None and deadline > as_of and any(r in _PREMATURE for r in reasons):
        reasons = [Exclusion.PENDING_TARGET] + [r for r in reasons if r not in _PREMATURE]
        corrected = True
    if deadline is not None and deadline <= as_of and Exclusion.PENDING_TARGET in reasons:
        # Still "pending" after its deadline: it was missed.
        reasons = [Exclusion.MISSED_TARGET if r is Exclusion.PENDING_TARGET else r for r in reasons]
        corrected = True
    reasons = list(dict.fromkeys(reasons))
    if not reasons:
        return None, corrected, ()
    return min(reasons, key=_PRECEDENCE.__getitem__), corrected, tuple(r.value for r in reasons)


def _waterfall(level: Level, units: list[AttritionUnit], *, as_of: datetime, not_applicable: set[Stage],
               enumerated: bool) -> Waterfall:
    if not enumerated:
        return Waterfall(level.value, None, (), None, {}, (), None, False)
    ids = [u.unit_id for u in units]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"{level.value}: duplicate unit ids {dupes} would double count")
    primaries: dict[Exclusion, int] = {e: 0 for e in Exclusion}
    raw: dict[str, int] = {}
    corrected: list[str] = []
    survivors = 0
    for unit in units:
        primary, fixed, effective = _primary(unit, as_of, not_applicable)
        for r in effective:  # after deadline corrections: a corrected MISSED is counted as PENDING
            raw[r] = raw.get(r, 0) + 1
        if fixed:
            corrected.append(unit.unit_id)
        if primary is None:
            survivors += 1
        else:
            primaries[primary] += 1
    remaining = len(units)
    rows = []
    for exclusion in Exclusion:
        stage = STAGE_OF[exclusion]
        if stage in not_applicable:
            rows.append(WaterfallRow(exclusion.value, stage.value, None, remaining))
            continue
        remaining -= primaries[exclusion]
        rows.append(WaterfallRow(exclusion.value, stage.value, primaries[exclusion], remaining))
    reconciled = remaining == survivors and sum(primaries.values()) + survivors == len(units)
    if not reconciled:  # a programming error, never a data condition
        raise AssertionError(f"{level.value} waterfall does not reconcile")
    clusters = {u.cluster_id for u in units if u.cluster_id}
    return Waterfall(level.value, len(units), tuple(rows), survivors, dict(sorted(raw.items())),
                     tuple(sorted(corrected)), len(clusters) if clusters else None, reconciled)


def attrition_report(units: Iterable[AttritionUnit], *, as_of_utc: str, levels_enumerated: Iterable[Level],
                     not_applicable_stages: Iterable[Stage] = ()) -> AttritionReport:
    """Deterministic attrition waterfalls, one per enumerated level, and the headline denominators.

    `levels_enumerated` says which levels the caller actually enumerated: an enumerated level
    with no units is 0, one that was not enumerated is None (unknown). A unit's primary
    reason is its earliest reason in `Exclusion` order, after any premature miss is corrected
    to PENDING_TARGET. Stages in `not_applicable_stages` (for example FILL for a calibration
    protocol) report None, never 0."""
    as_of = parse_utc(as_of_utc)
    if as_of is None:
        raise ValueError("as_of_utc must be a timezone-aware time")
    not_applicable = set(not_applicable_stages)
    enumerated = set(levels_enumerated)
    grouped: dict[Level, list[AttritionUnit]] = {level: [] for level in Level}
    for unit in units:
        if unit.level not in enumerated:
            raise ValueError(f"unit {unit.unit_id} is at level {unit.level.value}, which was not declared enumerated")
        grouped[unit.level].append(unit)
    waterfalls = tuple(_waterfall(level, grouped[level], as_of=as_of, not_applicable=not_applicable,
                                  enumerated=level in enumerated) for level in Level)
    by_level = {w.level: w for w in waterfalls}
    opp = by_level[Level.OPPORTUNITY.value]

    def after(stages: set[Stage]) -> int | None:
        if opp.start is None:
            return None
        excluded = sum(r.primary_count or 0 for r in opp.rows if Stage(r.stage) in stages)
        return opp.start - excluded

    eligible = after(_BEFORE_ELIGIBLE)
    signals = None if Stage.SIGNAL in not_applicable else after(_BEFORE_ELIGIBLE | {Stage.SIGNAL})
    fills = None if Stage.FILL in not_applicable else after(_BEFORE_ELIGIBLE | {Stage.SIGNAL, Stage.FILL})
    denominators = {
        "events": by_level[Level.EVENT.value].start,
        "markets": by_level[Level.MARKET.value].start,
        "scheduled_horizons": by_level[Level.HORIZON.value].start,
        "snapshots": by_level[Level.SNAPSHOT.value].start,
        "opportunities": opp.start,
        "eligible_opportunities": eligible,
        "signals": signals,
        "simulated_fills": fills,
        "final_evaluable_outcomes": None if Stage.OUTCOME in not_applicable else opp.survivors,
    }
    body = {"version": ATTRITION_VERSION, "as_of_utc": as_of.isoformat(),
            "not_applicable_stages": sorted(s.value for s in not_applicable),
            "denominators": denominators, "waterfalls": _plain([asdict(w) for w in waterfalls])}
    return AttritionReport(ATTRITION_VERSION, as_of.isoformat(), tuple(sorted(s.value for s in not_applicable)),
                           denominators, waterfalls, sha256_hex(canonical_json(body)))
