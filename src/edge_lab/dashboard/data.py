"""Read-only data access for the dashboard.

Every figure comes from a canonical module: the shadow ledger's replay, `risk.assess`,
`risk.withdrawal_assessment`, `outcome_board.build_board`, `forward.summary`, the fee
schedule registry and the experiment registry. Nothing here computes a balance, a limit
or a P&L of its own.

Every source is optional. A source that is not configured is `NO_DATA`; one that cannot be
read is `ERROR` with a short message that never contains a traceback or a full path.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from functools import cached_property
from pathlib import Path
from typing import Any, Callable

from .. import exp001_shadow, experiments as registry, fee_schedules, forward, risk, starter_policy, venues
from ..freshness import Freshness, assess as assess_freshness, parse_utc
from ..outcome_board import build_board
from ..shadow_ledger import AccountState, LedgerError, ShadowLedger
from ..storage import ReadOnlyStoreError, SnapshotStore

OK, NO_DATA, ERROR = "OK", "NO_DATA", "ERROR"
STATUS_MAX_AGE = timedelta(hours=26)
STATUS_FILE_MAX_BYTES = 2_000_000
COLLECTOR_STATUS_FILE = "latest.json"
RECEIPT_FILE = "shadow_daily.json"
NOTIFICATIONS_FILE = "notifications.jsonl"
NOTIFICATIONS_SHOWN = 50
FAILURE_FILE = "last_failure.json"  # production unit failures only (alert.sh; verification.FAILURE_NAME)
VERIFICATION_FILE = "last_verification.json"  # install-time checks (runbook §4.1; verification.VERIFICATION_NAME)
ODDS_LEDGER_FILE = "odds_quota_ledger.json"  # the Odds API quota ledger, beside the evidence database
FRESHNESS_FILE = "freshness.json"  # the Freshness Fabric supervisor's artifact (freshness_fabric.ARTIFACT_NAME)
RECEIPT_SCHEMA = "edge-lab-shadow-daily-receipt/1"

OPERATIONAL_ACCOUNT_ID = exp001_shadow.ACCOUNT_ID
RESEARCH_ACCOUNT_ID = getattr(exp001_shadow, "RESEARCH_ACCOUNT_ID", "EXP-001-stage-b-research")

# Which canonical risk policy governs which account. Only policies that exist in code are
# listed; an account without one shows "no registered policy", never an invented limit.
_POLICIES = {OPERATIONAL_ACCOUNT_ID: exp001_shadow.RISK_POLICY}
if getattr(exp001_shadow, "RESEARCH_RISK_POLICY", None) is not None:
    _POLICIES[RESEARCH_ACCOUNT_ID] = exp001_shadow.RESEARCH_RISK_POLICY


@dataclass(frozen=True)
class AccountRole:
    label: str
    note: str


ROLES = {
    OPERATIONAL_ACCOUNT_ID: AccountRole(
        "OPERATIONAL", "operational shadow account: EXP-001 signal under the sizing policy and risk limits"),
    RESEARCH_ACCOUNT_ID: AccountRole(
        "RESEARCH (FROZEN EXP-001 RULE)", "frozen EXP-001 research account: preregistered 1-contract rule, "
        "never re-tuned; the evidence for the experiment"),
}
KNOWN_ACCOUNTS = (OPERATIONAL_ACCOUNT_ID, RESEARCH_ACCOUNT_ID)


@dataclass(frozen=True)
class Config:
    db: Path | None = None
    ledger: Path | None = None
    status_dir: Path | None = None
    experiments_root: Path | None = None
    odds_ledger: Path | None = None  # The Odds API quota ledger; default: ODDS_LEDGER_FILE beside `db`
    demo: bool = False
    allowed_hosts: tuple[str, ...] = ()  # extra Host names accepted besides loopback (the bound host)
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))

    def paths(self) -> list[Path]:
        return [p for p in (self.db, self.ledger, self.status_dir, self.experiments_root, self.odds_ledger)
                if p is not None]


@dataclass
class Loaded:
    status: str  # OK | NO_DATA | ERROR
    value: Any = None
    message: str = ""


# --------------------------------------------------------------------------- safe messages

_ABS_PATH = re.compile(r"(?:[A-Za-z]:)?(?:[\\/][^\s\\/:'\"]+)+[\\/]?")


def short_error(exc: BaseException, config: Config | None = None, limit: int = 200) -> str:
    """A one-line message: the exception class and its text with every path reduced to its
    final name. No traceback, no directories, no environment values."""
    text = scrub_paths(str(exc).splitlines()[0] if str(exc) else "", config)
    text = f"{type(exc).__name__}: {text}" if text else type(exc).__name__
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _name(path: Path | None) -> str:
    return path.name if path is not None else "(not configured)"


# --------------------------------------------------------------------------- freshness


def freshness(ts: Any, now: datetime, max_age: timedelta = STATUS_MAX_AGE) -> tuple[str, timedelta | None]:
    """(FRESH | STALE | UNKNOWN, age) via the canonical freshness rule."""
    value = ts if isinstance(ts, str) else None
    state: Freshness = assess_freshness(value, max_age=max_age, now=now)
    parsed = parse_utc(value)
    return state.value.upper(), (now - parsed if parsed is not None else None)


# --------------------------------------------------------------------------- per-request context


@dataclass
class AccountView:
    account_id: str
    role: AccountRole | None
    status: str  # OK | NOT_STARTED | ERROR
    message: str = ""
    state: AccountState | None = None
    opened: dict[str, Any] = field(default_factory=dict)  # the account_opened payload
    decisions: list[dict[str, Any]] = field(default_factory=list)
    fills: dict[str, dict[str, Any]] = field(default_factory=dict)  # decision_id -> fill payload
    settlements: dict[str, dict[str, Any]] = field(default_factory=dict)  # fill_id -> settlement payload
    policy: Any = None
    risk: Loaded | None = None
    withdrawal: Loaded | None = None
    board: Loaded | None = None


class Context:
    """Everything one request may read, loaded lazily and at most once."""

    def __init__(self, config: Config) -> None:
        self.config = config
        now = config.clock()
        self.now = parse_utc(now) or datetime.now(timezone.utc)

    # ---- evidence store

    @cached_property
    def store(self) -> Loaded:
        path = self.config.db
        if path is None:
            return Loaded(NO_DATA, message="no evidence database configured (--db)")
        if not path.exists():
            return Loaded(NO_DATA, message=f"evidence database {path.name} does not exist: collection NOT STARTED "
                                           "here, or the path is wrong")
        try:
            return Loaded(OK, SnapshotStore.open_readonly(path))
        except ReadOnlyStoreError as exc:
            return Loaded(ERROR, message=short_error(exc, self.config))
        except Exception as exc:  # noqa: BLE001 - any failure is shown, never raised
            return Loaded(ERROR, message=short_error(exc, self.config))

    @cached_property
    def collector_db(self) -> Loaded:
        if self.store.status != OK:
            return self.store
        try:
            return Loaded(OK, forward.summary(self.store.value, now_utc=self.now))
        except Exception as exc:  # noqa: BLE001
            return Loaded(ERROR, message=short_error(exc, self.config))

    @cached_property
    def source_health(self) -> Loaded:
        if self.store.status != OK:
            return self.store
        try:
            rows = [dict(r) for r in self.store.value.latest_source_health()]
        except Exception as exc:  # noqa: BLE001
            return Loaded(ERROR, message=short_error(exc, self.config))
        if not rows:
            return Loaded(NO_DATA, message="no source-health rows recorded in the evidence database")
        return Loaded(OK, rows)

    # ---- status files

    def _status_file(self, name: str) -> Loaded:
        directory = self.config.status_dir
        if directory is None:
            return Loaded(NO_DATA, message="no status directory configured (--status-dir)")
        path = directory / name
        try:
            if not path.exists():
                return Loaded(NO_DATA, message=f"{name} not found in the status directory")
            if path.is_symlink() or not path.is_file():
                return Loaded(ERROR, message=f"{name} is not a regular file")
            if path.stat().st_size > STATUS_FILE_MAX_BYTES:
                return Loaded(ERROR, message=f"{name} is larger than {STATUS_FILE_MAX_BYTES} bytes")
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            return Loaded(ERROR, message=f"{name} cannot be read: {short_error(exc, self.config)}")
        if not isinstance(data, dict):
            return Loaded(ERROR, message=f"{name} is not a JSON object")
        return Loaded(OK, data)

    @cached_property
    def collector_status(self) -> Loaded:
        return self._status_file(COLLECTOR_STATUS_FILE)

    @cached_property
    def receipt(self) -> Loaded:
        return self._status_file(RECEIPT_FILE)

    @cached_property
    def last_failure(self) -> Loaded:
        return self._status_file(FAILURE_FILE)

    @cached_property
    def last_verification(self) -> Loaded:
        return self._status_file(VERIFICATION_FILE)

    @cached_property
    def failure_records(self) -> list["FailureRecord"]:
        """Both unit-failure records, each classified by origin (see `classify_failure`)."""
        out = []
        for name, loaded in ((FAILURE_FILE, self.last_failure), (VERIFICATION_FILE, self.last_verification)):
            if loaded.status == OK:
                out.append(classify_failure(name, loaded.value))
            elif loaded.status == ERROR:
                out.append(FailureRecord(name, {}, None, False, loaded.message))
        return out

    @cached_property
    def odds_status(self) -> Loaded:
        """`odds_pilot.dashboard_status` for The Odds API pilot (read-only, no key, no network)."""
        from .. import odds_pilot

        if self.config.db is None:
            return Loaded(NO_DATA, message="no evidence database configured (--db), so the Odds API pilot's "
                                           "evidence cannot be read")
        ledger = self.config.odds_ledger or self.config.db.with_name(ODDS_LEDGER_FILE)
        # The runner keeps its non-secret state beside the ledger (odds_pilot.PilotState).
        state = ledger.with_name(ledger.name + ".pilot.json")
        try:
            return Loaded(OK, odds_pilot.dashboard_status(self.config.db, ledger, state, now=self.now))
        except Exception as exc:  # noqa: BLE001 - shown as an error state, never raised
            return Loaded(ERROR, message=short_error(exc, self.config))

    @cached_property
    def freshness_status(self) -> Loaded:
        """The Freshness Fabric supervisor's current-state artifact (`freshness.json`, schema
        `freshness-fabric-status/1`), read as written: OK with a `FreshnessReport`, NO_DATA when not
        configured or not written yet, ERROR when unreadable or of another schema."""
        return freshness_report(self)

    @cached_property
    def pm_sports(self) -> Loaded:
        """Lane B's Polymarket US NFL pilot view (`pm_sports_view`)."""
        return pm_sports_view(self)

    @cached_property
    def economic_a(self) -> Loaded:
        """Economic Evidence v1, Family A: `sports_evidence.terminal_view` (`economic_evidence_a`)."""
        return economic_evidence_a(self)

    @cached_property
    def economic_b(self) -> Loaded:
        """Economic Evidence v1, Family B: the same-venue payoff evaluator's view, when installed."""
        return economic_evidence_b(self)

    @cached_property
    def odds_targets(self) -> Loaded:
        """The Odds API pilot's capture targets and their history (`odds_capture_targets`)."""
        return odds_capture_targets(self)

    @cached_property
    def notifications(self) -> Loaded:
        """The newest local-outbox notifications (JSON lines), newest first."""
        directory = self.config.status_dir
        if directory is None:
            return Loaded(NO_DATA, message="no status directory configured (--status-dir)")
        path = directory / NOTIFICATIONS_FILE
        try:
            if not path.exists():
                return Loaded(NO_DATA, message="no notifications have been written yet")
            if path.is_symlink() or not path.is_file():
                return Loaded(ERROR, message=f"{NOTIFICATIONS_FILE} is not a regular file")
            if path.stat().st_size > STATUS_FILE_MAX_BYTES:
                return Loaded(ERROR, message=f"{NOTIFICATIONS_FILE} is larger than {STATUS_FILE_MAX_BYTES} bytes")
            rows = []
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
        except (OSError, UnicodeDecodeError) as exc:
            return Loaded(ERROR, message=f"{NOTIFICATIONS_FILE} cannot be read: {short_error(exc, self.config)}")
        return Loaded(OK, list(reversed(rows))[:NOTIFICATIONS_SHOWN])

    # ---- shadow ledger

    @cached_property
    def ledger(self) -> Loaded:
        path = self.config.ledger
        if path is None:
            return Loaded(NO_DATA, message="no shadow ledger configured (--ledger)")
        if not path.exists():
            return Loaded(NO_DATA, message=f"shadow ledger {path.name} does not exist: shadow trading NOT STARTED "
                                           "here, or the path is wrong")
        try:
            return Loaded(OK, ShadowLedger.open_readonly(path))
        except Exception as exc:  # noqa: BLE001 - LedgerError, sqlite errors
            return Loaded(ERROR, message=short_error(exc, self.config))

    @cached_property
    def ledger_accounts(self) -> Loaded:
        if self.ledger.status != OK:
            return self.ledger
        try:
            return Loaded(OK, self.ledger.value.accounts())
        except Exception as exc:  # noqa: BLE001
            return Loaded(ERROR, message=short_error(exc, self.config))

    @cached_property
    def accounts(self) -> list[AccountView]:
        """Both known accounts always appear, plus any other account the ledger holds."""
        found = self.ledger_accounts.value if self.ledger_accounts.status == OK else []
        ids = list(KNOWN_ACCOUNTS) + [a for a in found if a not in KNOWN_ACCOUNTS]
        return [self._account(a, a in found) for a in ids]

    def _account(self, account_id: str, present: bool) -> AccountView:
        view = AccountView(account_id, ROLES.get(account_id), "NOT_STARTED", policy=_POLICIES.get(account_id))
        if self.ledger_accounts.status != OK:
            view.status = self.ledger_accounts.status if self.ledger_accounts.status == ERROR else "NOT_STARTED"
            view.message = self.ledger_accounts.message
            return view
        if not present:
            view.message = f"account {account_id} has not been opened in {_name(self.config.ledger)}"
            return view
        try:
            rows = self.ledger.value.entries(account_id)
            view.state = self.ledger.value.state(account_id)
        except Exception as exc:  # noqa: BLE001 - a broken chain or invariant is an ERROR, not zeros
            view.status, view.message = ERROR, short_error(exc, self.config)
            return view
        view.status = OK
        for row in rows:
            payload = json.loads(row["payload_json"])
            meta = {"entry_key": row["entry_key"], "effective_at_utc": row["effective_at_utc"],
                    "appended_at_utc": row["appended_at_utc"]}
            if row["kind"] == "account_opened":
                view.opened = payload
            elif row["kind"] == "decision":
                view.decisions.append({**payload, "_meta": meta})
            elif row["kind"] == "fill":
                view.fills[payload.get("decision_id")] = {**payload, "_meta": meta}
            elif row["kind"] == "settlement":
                view.settlements[payload.get("fill_id")] = {**payload, "_meta": meta}
        view.risk = self._risk(view)
        view.withdrawal = self._withdrawal(view)
        view.board = self._board(view)
        return view

    def _risk(self, view: AccountView) -> Loaded:
        if view.policy is None:
            return Loaded(NO_DATA, message="no risk policy is registered in code for this account; risk figures "
                                           "are not computed (not zero)")
        try:
            return Loaded(OK, risk.assess(view.state, view.policy, self.now))
        except ValueError as exc:
            return Loaded(ERROR, message=short_error(exc, self.config))

    def _withdrawal(self, view: AccountView) -> Loaded:
        if view.risk is None or view.risk.status != OK:
            return Loaded(NO_DATA, message="needs a risk report")
        return Loaded(OK, risk.withdrawal_assessment(
            view.state, view.risk.value, simulation=True, edge_verified=False,
            fee_claim_basis=fee_schedules.recorded_claim_basis(view.fills.values()).value,
            owner_policy_approved=False))

    def _board(self, view: AccountView) -> Loaded:
        try:
            return Loaded(OK, build_board(view.state, self.now, include_settled=True))
        except ValueError as exc:
            return Loaded(ERROR, message=short_error(exc, self.config))

    # ---- observed quotes

    @cached_property
    def observed(self) -> Loaded:
        """The latest captured market list and books (`observed_board`)."""
        if self.store.status != OK:
            return self.store
        try:
            board = observed_board(self.store.value)
        except Exception as exc:  # noqa: BLE001
            return Loaded(ERROR, message=short_error(exc, self.config))
        if board is None:
            return Loaded(NO_DATA, message="no market books have been captured in the evidence database yet")
        return Loaded(OK, board)

    def account(self, account_id: str) -> AccountView:
        """One account's view (both known accounts always exist, possibly NOT_STARTED)."""
        return next(v for v in self.accounts if v.account_id == account_id)

    # ---- experiments

    @cached_property
    def experiments(self) -> Loaded:
        root = self.config.experiments_root
        if root is None:
            return Loaded(NO_DATA, message="no experiments directory configured (--experiments-root)")
        if not root.is_dir():
            return Loaded(NO_DATA, message=f"experiments directory {root.name} not found")
        try:
            problems = registry.validate_all(root)
            out = []
            for path in registry.discover(root):
                key = str(path.relative_to(root))
                try:
                    exp = registry.load(path)
                except (tomllib.TOMLDecodeError, OSError) as exc:
                    out.append({"key": key, "id": None, "title": None, "status": None,
                                "problems": [short_error(exc, self.config)], "stage_a": None, "reports": []})
                    continue
                periods = exp.data.get("periods") if isinstance(exp.data.get("periods"), dict) else {}
                out.append({"key": key, "id": exp.id, "title": exp.data.get("title"), "status": exp.status,
                            "problems": problems.get(key, []), "stage_a": _stage_a(path.parent),
                            "reports": _reports(path.parent), "stage_b_plan": periods.get("stage_b"),
                            "limitations": exp.data.get("limitations") if isinstance(exp.data.get("limitations"),
                                                                                    list) else []})
        except Exception as exc:  # noqa: BLE001
            return Loaded(ERROR, message=short_error(exc, self.config))
        return Loaded(OK, out)


@dataclass(frozen=True)
class FailureRecord:
    """One unit-failure record and how to present it. last_failure.json holds production failures
    only (alert.sh). `verification` is True only for a last_verification.json record that says
    DEPLOYMENT_VERIFICATION *and* that root confirmed (`verification.verification_confirmed`); an
    unconfirmed one is shown as an unproven or expired check, never as an incident. `origin` is the
    record's origin value (None: an unrecognised value)."""

    source: str  # FAILURE_FILE | VERIFICATION_FILE
    record: dict[str, Any]
    origin: str | None
    verification: bool
    error: str | None = None  # the record could not be read


def classify_failure(source: str, record: dict[str, Any]) -> FailureRecord:
    from .. import notifications, verification

    origin = notifications.origin_of(record)
    confirmed = (source == VERIFICATION_FILE and origin is notifications.Origin.DEPLOYMENT_VERIFICATION
                 and verification.verification_confirmed(record))
    return FailureRecord(source, record, None if origin is None else origin.value, bool(confirmed))


def fee_state(now: datetime) -> fee_schedules.FeeVerificationState:
    """The active schedule's verification for the EXP-001 series as known at `now`."""
    return fee_schedules.verification_at(exp001_shadow.stageb.FEE_SCHEDULE, now, scope=forward.SERIES)


def fee_rows(now: datetime) -> list[dict[str, Any]]:
    """One row per schedule with the verification known at `now` (ADR 0017)."""
    active = exp001_shadow.stageb.FEE_SCHEDULE.schedule_id
    rows = []
    for s in fee_schedules.FEE_SCHEDULES.values():
        v = fee_schedules.verification_at(s, now, scope=forward.SERIES)
        record = next((r for r in fee_schedules.FEE_VERIFICATIONS if r.verification_id == v.verification_id), None)
        rows.append({"schedule_id": s.schedule_id, "venue": s.venue, "status": v.status.value,
                     "claimable": v.claimable, "claim_basis": v.claim_basis.value,
                     "claim_allowance_per_contract": None if v.rounding_allowance_per_contract is None
                     else str(v.rounding_allowance_per_contract),
                     "verification_id": v.verification_id, "detail": v.detail,
                     "recheck_by_utc": record.recheck_by_utc if record else None,
                     "components": [{"component": c.component.value, "state": c.state.value,
                                     "detail": c.detail, "evidence": c.evidence}
                                    for c in (record.components if record else ())],
                     "checked_at_utc": record.knowledge_time_utc if record else s.checked_at_utc,
                     "evidence": s.evidence, "active": s.schedule_id == active})
    return rows


def _stage_a(exp_dir: Path) -> dict[str, Any] | None:
    """Selected fields of a recorded Stage A result, when one exists. Read, never recomputed."""
    path = exp_dir / "gate4" / "stage_a_result.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"verdict": None, "error": "stage_a_result.json cannot be parsed"}
    if not isinstance(data, dict):
        return {"verdict": None, "error": "stage_a_result.json is not a JSON object"}
    conditions = {k: (v.get("passed") if isinstance(v, dict) else None)
                  for k, v in data.items() if k.startswith("condition_")}
    window = data.get("test_window") if isinstance(data.get("test_window"), dict) else {}
    return {"verdict": data.get("verdict"), "phase": data.get("phase"), "n_test_days": data.get("n_test_days"),
            "selected_variant": data.get("selected_variant"), "conditions": conditions,
            "test_first": window.get("first"), "test_last": window.get("last"),
            "dataset_sha256": data.get("dataset_sha256")}


def _reports(exp_dir: Path) -> list[str]:
    """Names of gate reports (Markdown) under the experiment. Names only; nothing is served."""
    return sorted(str(p.relative_to(exp_dir)) for p in exp_dir.glob("gate*/*.md") if p.is_file())


def starter_view(view: AccountView, now: datetime) -> dict[str, Any] | None:
    """STARTER_MAX_7D_V1 for an operational account, from its recorded fills (read-only)."""
    account = next((a for a in exp001_shadow.ACCOUNTS if a.account_id == view.account_id), None)
    if account is None or not account.starter_policy or view.state is None:
        return None
    fills = list(view.fills.values())
    open_ids = {p.position_id for p in view.state.open_positions()}
    return {"policy_id": starter_policy.POLICY_ID, "effective_from_utc": starter_policy.EFFECTIVE_FROM_UTC,
            "max_hours": int(starter_policy.MAX_HORIZON.total_seconds() // 3600),
            "verdicts": [f for f in fills if isinstance(f.get("starter_policy"), dict)],
            "exceptions": starter_policy.policy_exceptions(fills, open_ids, now)}


def venue_rows() -> list[dict[str, Any]]:
    return venues.coverage_rows()



# --------------------------------------------------------------------------- observed quotes (evidence store)

QUOTE_PHASES = ("decision", "recheck")  # the forward collector's two book captures per target day
MAX_OBSERVED_MARKETS = 200


@dataclass(frozen=True)
class ObservedQuote:
    """One side of one captured book, normalized by `kalshi_quotes.quotes_from_orderbook`.

    `ask` is the executable buy price for `side` as captured; nothing here is a midpoint,
    last trade or mark."""

    side: str
    ask: Any  # Decimal | None
    bid: Any
    size: Any  # quantity offered at exactly `ask`
    received_at_utc: str | None
    evidence_id: str | None
    anomaly: str | None


@dataclass
class ObservedMarket:
    venue: str
    market_id: str  # "<venue>:<native id>"
    native_id: str
    event_ticker: str | None
    event_id: str | None
    domain: str | None
    target_date: str
    title: str | None
    outcome: str | None  # the YES outcome label as the venue states it
    no_outcome: str | None
    status: str | None  # venue lifecycle word as captured
    close_time_utc: str | None
    rules_primary: str | None
    payoff_kind: str | None
    quotes: dict[str, dict[str, ObservedQuote]] = field(default_factory=dict)  # phase -> side -> quote
    raw: dict[str, Any] | None = field(default=None, repr=False)  # the decision capture's market listing
    books: dict[str, "BookEvidence"] = field(default_factory=dict, repr=False)  # phase -> the captured book


@dataclass(frozen=True)
class BookEvidence:
    """One captured order-book snapshot as stored (the comparator builds its depth ladders from it)."""

    payload: dict[str, Any]
    received_at_utc: str | None
    evidence_id: str
    url: str | None
    capture_id: int


@dataclass
class ObservedBoard:
    target_date: str
    captures: dict[str, dict[str, Any]]  # phase -> {id, status, completed_at_utc, reasons}
    markets: list[ObservedMarket]
    total_markets: int = 0  # before the MAX_OBSERVED_MARKETS cap; shown when the board is truncated

    @property
    def complete(self) -> bool:
        """True only when every phase used is a complete capture (partial ones are labelled)."""
        return bool(self.captures) and all(c.get("status") == "complete" for c in self.captures.values())


def _capture_for(rows: list, phase: str) -> Any:
    """The complete capture of a phase if there is one, else the latest that stored any books."""
    mine = [r for r in rows if r["phase"] == phase]
    complete = [r for r in mine if r["status"] == "complete"]
    if complete:
        return complete[-1]
    with_books = [r for r in mine if (json.loads(r["links_json"] or "{}").get("books"))]
    return with_books[-1] if with_books else None


def observed_board(store: SnapshotStore, *, mode: str = "live") -> ObservedBoard | None:
    """The latest target day's captured markets and books, read-only. None when nothing is captured.

    Market metadata comes from the decision capture's market snapshots; books from each
    phase's own snapshots (only snapshots written by that capture's run count, as in
    `exp001_stageb.evaluate_day`). Quotes are normalized by the canonical Kalshi adapter."""
    from ..exp001_stageb import event_for
    from ..kalshi_quotes import VENUE, market_from_kalshi, quotes_from_orderbook

    rows = [r for r in store.forward_captures(mode=mode) if r["phase"] in QUOTE_PHASES]
    targets = sorted({r["target_date"] for r in rows if json.loads(r["links_json"] or "{}").get("books")})
    if not targets:
        return None
    target = targets[-1]
    day_rows = [r for r in rows if r["target_date"] == target]
    try:
        event = event_for(datetime.fromisoformat(target).date())
        domain, event_id = event.domain, event.event_id
    except ValueError:
        domain = event_id = None
    markets: dict[str, ObservedMarket] = {}
    captures: dict[str, dict[str, Any]] = {}
    for phase in QUOTE_PHASES:
        row = _capture_for(day_rows, phase)
        if row is None:
            continue
        links = json.loads(row["links_json"] or "{}")
        captures[phase] = {"id": int(row["id"]), "status": row["status"], "completed_at_utc": row["completed_at_utc"],
                           "reasons": json.loads(row["reasons_json"] or "[]")}
        books = links.get("books") or {}
        ids = [*links.get("market_snapshots", []), *(b.get("snapshot_id") for b in books.values())]
        snaps = {sid: s for sid, s in store.snapshots_by_id(i for i in ids if i is not None).items()
                 if s["run_id"] == row["run_id"]}
        for sid in links.get("market_snapshots", []):
            snap = snaps.get(sid)
            if snap is None:
                continue
            for raw in json.loads(snap["payload_json"]).get("markets") or []:
                if not isinstance(raw, dict) or not raw.get("ticker"):
                    continue
                m = market_from_kalshi(raw, event_id_for_ticker={})
                known = markets.setdefault(m.market_id, ObservedMarket(
                    venue=VENUE, market_id=m.market_id, native_id=m.native_id,
                    event_ticker=raw.get("event_ticker"), event_id=event_id, domain=domain, target_date=target,
                    title=raw.get("title"), outcome=raw.get("yes_sub_title") or m.outcome,
                    no_outcome=raw.get("no_sub_title"), status=raw.get("status"), close_time_utc=raw.get("close_time"),
                    rules_primary=raw.get("rules_primary"), payoff_kind=m.payoff.kind))
                if phase == "decision" and known.raw is None:
                    known.raw = raw  # the listing the decision engine read (the comparator's contract fields)
        for native, info in books.items():
            snap = snaps.get(info.get("snapshot_id"))
            if snap is None or snap["entity_id"] != native or snap["kind"] != "orderbook":
                continue
            payload = json.loads(snap["payload_json"])
            quotes = quotes_from_orderbook(native, payload,
                                           received_at_utc=snap["fetched_at_utc"], evidence_id=f"snapshot:{snap['id']}")
            if not quotes:
                continue
            mid = next(iter(quotes.values())).market_id
            market = markets.setdefault(mid, ObservedMarket(
                venue=VENUE, market_id=mid, native_id=native, event_ticker=None, event_id=event_id, domain=domain,
                target_date=target, title=None, outcome=None, no_outcome=None, status=None, close_time_utc=None,
                rules_primary=None, payoff_kind=None))
            market.books[phase] = BookEvidence(payload if isinstance(payload, dict) else {}, snap["fetched_at_utc"],
                                               f"snapshot:{snap['id']}", snap["url"], int(row["id"]))
            market.quotes[phase] = {side: ObservedQuote(side, q.best_ask, q.best_bid, q.displayed_size,
                                                        q.received_at_utc, q.evidence_id, q.anomaly)
                                    for side, q in quotes.items()}
    ordered = sorted(markets.values(), key=lambda m: m.market_id)
    return ObservedBoard(target, captures, ordered[:MAX_OBSERVED_MARKETS], len(ordered))


# --------------------------------------------------------------------------- research sizing (sizing_counterfactual)

RESEARCH_SIZING_MODULE = "edge_lab.sizing_counterfactual"


def _sizing_module(ctx: Context) -> tuple[Any, Loaded | None]:
    """The research sizing contract, or the state that replaces it (not installed / broken)."""
    import importlib

    try:
        return importlib.import_module(RESEARCH_SIZING_MODULE), None
    except ModuleNotFoundError as exc:
        if exc.name != RESEARCH_SIZING_MODULE:  # installed, but one of its own imports is missing
            return None, Loaded(ERROR, message=short_error(exc, ctx.config))
        return None, Loaded(NO_DATA, message="the research sizing contract (sizing_counterfactual) is not installed "
                                             "in this build")
    except Exception as exc:  # noqa: BLE001 - a module that fails to import is broken, not absent
        return None, Loaded(ERROR, message=short_error(exc, ctx.config))


def research_sizing(ctx: Context, market_id: str) -> Loaded:
    """Lane A's read-only research sizing panel for one market: OK with the panel dict (which may
    itself be unavailable with a named reason), NO_DATA when the contract is not installed or no
    ledger is configured, ERROR on a read failure or a broken contract.

    One `build_panel_bundle` replay per request serves every market on the page; the contract
    memoizes it across requests (ledger heads, evidence DB snapshot id, config, code), so the
    dashboard keeps no cache of its own. A replay made without a readable evidence database
    carries a caveat in `message`. Nothing here sizes or edits a figure; free-text details are
    only scrubbed of paths."""
    module, problem = _sizing_module(ctx)
    if problem is not None:
        return problem
    if ctx.ledger.status == ERROR:
        return Loaded(ERROR, message=ctx.ledger.message)
    if ctx.ledger.status != OK:
        return Loaded(NO_DATA, message=ctx.ledger.message or "no shadow ledger configured")
    store = ctx.store.value if ctx.store.status == OK else None
    caveat = ""
    if ctx.store.status != OK:
        why = "cannot be read" if ctx.store.status == ERROR else "is not available"
        caveat = (f"Replayed without the evidence database, which {why} ({ctx.store.message}): captured "
                  "settlements and confirmation quotes are missing from this replay.")
    try:
        if hasattr(module, "build_panel_bundle") and hasattr(module, "panel_for_market_from_bundle"):
            bundle = ctx.__dict__.get("_sizing_bundle")
            if bundle is None:
                bundle = ctx.__dict__["_sizing_bundle"] = module.build_panel_bundle(store, ctx.ledger.value)
            panel = module.panel_for_market_from_bundle(bundle, market_id)
        else:
            panel = module.panel_for_market(store, ctx.ledger.value, market_id)
    except Exception as exc:  # noqa: BLE001 - the contract never raises for missing data; anything else is shown
        return Loaded(ERROR, message=short_error(exc, ctx.config))
    if not isinstance(panel, dict):
        return Loaded(ERROR, message="the research sizing contract returned no panel")
    return Loaded(OK, _scrubbed(panel, ctx.config), message=caveat)


def scrub_paths(text: Any, config: Config | None = None) -> Any:
    """A free-text detail with every filesystem path reduced to its final name (as `short_error`)."""
    if not isinstance(text, str):
        return text
    for p in (config.paths() if config else []):
        for variant in {str(p), str(p.resolve())}:
            text = text.replace(variant, p.name)
    return _ABS_PATH.sub(lambda m: re.split(r"[\\/]", m.group(0).rstrip("\\/"))[-1], text)


def _scrubbed(panel: dict[str, Any], config: Config) -> dict[str, Any]:
    """A copy of the panel whose free-text `unavailable_detail`s carry no paths (engine text may quote
    an OS error). Figures and every other field are untouched."""
    out = dict(panel, unavailable_detail=scrub_paths(panel.get("unavailable_detail"), config))
    sides = panel.get("sides")
    if isinstance(sides, list):
        out["sides"] = [dict(s, unavailable_detail=scrub_paths(s.get("unavailable_detail"), config))
                        if isinstance(s, dict) else s for s in sides]
    return out


# --------------------------------------------------------------------------- across venues (best_price, ADR 0027)

COMPARISON_PHASE = "decision"  # the capture whose books the recorded decision read


@dataclass(frozen=True)
class VenueComparison:
    """The canonical comparator's result for one market, side and evaluated size, or why none exists.

    status: OK (comparison holds a `best_price.Comparison`) | NOT_EVALUATED (no evaluated size or
    decision time) | NO_DATA (nothing captured to compare) | ERROR (a read or input failure).
    Every figure shown comes from `comparison`; the dashboard computes none of them."""

    status: str
    message: str = ""
    comparison: Any = None
    quantity: Any = None
    as_of_utc: str | None = None
    book_phase: str = COMPARISON_PHASE


def _depth_limit(url: str | None) -> int | None:
    """The `depth` the book was requested with, from the stored request URL; None when the URL does
    not say. The caller treats an unknown depth as possibly truncated (fail closed), so a ladder
    that runs out reads DEPTH_UNKNOWN, never "the complete book offers less"."""
    from urllib.parse import parse_qsl, urlsplit

    for key, value in parse_qsl(urlsplit(url or "").query):
        if key == "depth" and value.isascii() and value.isdecimal():
            return int(value)
    return None


def venue_comparison(ctx: Context, market_id: str, side: str, quantity: Any, as_of_utc: str | None,
                     evidence_ids: Any = ()) -> VenueComparison:
    """Run `best_price.compare` for one captured market at its recorded decision time and size.

    Inputs come only from stored evidence through the canonical adapters, built as
    `exp001_stageb.evaluate_day` builds them: the decision capture's market listing
    (`kalshi_quotes.market_from_kalshi`, with the same `settlement_equivalence` downgrade of
    `rules_resolved`), its captured book for `side` (`kalshi_quotes.ladders_from_orderbook`, depth
    limit from the stored request URL; an unknown depth counts as truncated), the fee schedule for the market's own
    series (`fee_schedules.schedule_for`) and the engine's book-age limit. When the decision
    recorded its quote evidence ids (`evidence_ids`), the book must be one of them. The routes are
    every captured route for this market; today only its own venue is captured, so no other venue
    is ever compared or ranked."""
    from decimal import Decimal, InvalidOperation

    from .. import best_price
    from ..discovery import _series_scope  # the comparator's own scope rule (best_price uses it too)
    from ..exp001_stageb import STAGE_B_POLICY, event_for, settlement_equivalence
    from ..kalshi_quotes import ladders_from_orderbook, market_from_kalshi

    try:
        qty = Decimal(str(quantity)) if quantity is not None and not isinstance(quantity, bool) else None
    except InvalidOperation:
        qty = None
    if qty is not None and qty.is_finite() and qty == 0:
        return VenueComparison("NOT_EVALUATED", "the recorded size for this side is 0 contracts, so there is nothing "
                                                "to compare", quantity=qty)
    if qty is None or not qty.is_finite() or qty < 0:
        return VenueComparison("NOT_EVALUATED", "no size was evaluated for this side, so there is no requested size "
                                                "to compare")
    at = parse_utc(as_of_utc)
    if at is None:
        return VenueComparison("NOT_EVALUATED", "the decision time is not recorded", quantity=qty)
    if ctx.observed.status == ERROR:
        return VenueComparison(ERROR, ctx.observed.message, quantity=qty, as_of_utc=at.isoformat())
    if ctx.observed.status != OK:
        return VenueComparison(NO_DATA, ctx.observed.message or "no market books captured", quantity=qty,
                               as_of_utc=at.isoformat())
    board = ctx.observed.value
    market = next((m for m in board.markets if m.market_id == market_id), None)
    if market is None and board.total_markets > len(board.markets):
        return VenueComparison(NO_DATA, f"this market is not among the {len(board.markets)} captured markets the "
                                        "dashboard reads (the capture holds more; it may be beyond that cap)", quantity=qty, as_of_utc=at.isoformat())
    if market is None or market.raw is None:
        return VenueComparison(NO_DATA, "the decision capture holds no market listing for this market",
                               quantity=qty, as_of_utc=at.isoformat())
    book = market.books.get(COMPARISON_PHASE)
    recorded = [str(e) for e in evidence_ids if e] if isinstance(evidence_ids, (list, tuple)) else []
    if book is not None and recorded and book.evidence_id not in recorded:
        return VenueComparison(NO_DATA, f"the captured book ({book.evidence_id}) is not the one the decision read "
                                        f"({', '.join(recorded)})", quantity=qty, as_of_utc=at.isoformat())
    try:
        target = datetime.fromisoformat(market.target_date).date()
        event = event_for(target)
        # Only the expected event ticker maps to the normalized event (as in exp001_stageb.evaluate_day).
        mapping = {forward.event_ticker_for(target): event.event_id}
        contract = market_from_kalshi(market.raw, event_id_for_ticker=mapping,
                                      timing_source=None if book is None else f"decision_capture:{book.capture_id}")
        equivalent, why_not = settlement_equivalence(market.raw, target)
        if contract.rules_resolved and not equivalent:
            contract = replace(contract, rules_resolved=False, rules_detail=f"settlement equivalence: {why_not}")
        ladder = None
        if book is not None:
            limit = _depth_limit(book.url)
            ladder = ladders_from_orderbook(contract.native_id, book.payload, received_at_utc=book.received_at_utc,
                                            evidence_id=book.evidence_id, depth_limit=limit).get(side)
            if ladder is not None and limit is None:
                # Unknown request depth: the book may have been cut off, so it is never "complete".
                ladder = replace(ladder, truncated=True)
        route = best_price.Route(event, contract, ladder,
                                 fee_schedules.schedule_for(contract.venue, _series_scope(contract), as_of=at))
        result = best_price.compare(best_price.PositionRequest(event, contract, side, qty), [route], as_of=at,
                                    max_book_age=STAGE_B_POLICY.max_book_age)
    except Exception as exc:  # noqa: BLE001 - shown as an error state, never raised
        return VenueComparison(ERROR, short_error(exc, ctx.config), quantity=qty, as_of_utc=at.isoformat())
    return VenueComparison(OK, comparison=result, quantity=qty, as_of_utc=at.isoformat())


# --------------------------------------------------------------------------- The Odds API capture targets (ADR 0029)

ODDS_TARGETS_SHOWN = 5  # recent and next targets each, as rows; every other one is in the history table
ODDS_TARGETS_MAX = 400  # rows in the history table (the oldest are left out beyond this)
ODDS_PARSE_CACHE_MAX = 64  # parsed captures kept across requests (stored snapshots are immutable)
# Freshness of one target, beside the canonical FRESH / STALE / UNKNOWN of a captured response:
TARGET_OVERDUE = "TARGET_OVERDUE"  # open (not final) and past its canonical deadline: no outcome recorded since
TARGET_PENDING = "TARGET_PENDING"  # open and not yet past its deadline: nothing captured yet
TARGET_NO_CAPTURE = "TARGET_NO_CAPTURE"  # a final state other than CAPTURED: nothing was captured
NOT_EVALUATED = "NOT_EVALUATED"  # a history row whose captured response is not parsed on this page
BOOKS_PARSED, BOOKS_RECORDED = "parsed", "recorded"  # where a row's book count comes from


@dataclass(frozen=True)
class OddsTarget:
    """One stored capture target with its current (latest) transition, exactly as recorded
    (`SnapshotStore.odds_targets`), plus read-only facts from canonical functions:

    - `due_utc` / `deadline_utc`: `odds_schedule.effective_due` / `deadline` under the runner's config;
    - `freshness`: for a CAPTURED row shown as a row, the captured offers' freshness **at receipt**
      (`odds_api.offer_freshness` at the receipt time, worst of the event's offers by
      `freshness.combine`): a capture is historical evidence, never current data. A history-table row
      is NOT_EVALUATED (its response is not parsed there). Otherwise TARGET_OVERDUE, TARGET_PENDING,
      TARGET_NO_CAPTURE, or UNKNOWN for a state this code does not know;
    - `books` / `offers`: for rows shown, parsed from the captured snapshot by `odds_api.parse_odds`
      (`books_source` "parsed"); for history rows, the runner's own record at capture
      (`detail.bookmakers` / `detail.offers`, "recorded"). `()` is a known zero; `None` is unknown,
      with `books_note` saying why. A response with parse problems carries a caveat in `books_note`;
    - `shared_targets`: how many targets recorded the same paid call (snapshot), so a call's
      credits are never read as one charge per target.
    Nothing here is computed from prices; no figure is invented for a missing one."""

    target_id: str
    sport: str
    event_id: str
    offset_label: str
    priority: Any
    home_team: str | None
    away_team: str | None
    commence_utc: str | None
    target_utc: str | None
    planned_at_utc: str | None
    policy_version: str | None
    state: str
    state_at_utc: str | None
    reason: str | None
    slot_id: str | None
    snapshot_id: int | None
    captured_at_utc: str | None
    credits_last: int | None
    detail: dict[str, Any]
    due_utc: str | None = None
    deadline_utc: str | None = None
    freshness: str = "UNKNOWN"
    books: tuple[str, ...] | None = None
    offers: int | None = None
    books_note: str | None = None
    books_source: str | None = None
    shared_targets: int | None = None
    transitions: tuple[dict[str, Any], ...] | None = None  # loaded for the rows shown, else None
    consensus: "Loaded | None" = None  # CAPTURED rows shown: `odds_consensus_at_capture`, else None


@dataclass(frozen=True)
class OddsTargets:
    """The pilot sport's stored targets (canonical order: intended time, priority, event) and the
    bounded selection shown as rows: the latest `ODDS_TARGETS_SHOWN` whose intended time has passed
    (newest first) and the next `ODDS_TARGETS_SHOWN` still ahead. Only the captures behind those rows
    are parsed; `snapshots` keeps them (id -> `odds_api.OddsSnapshot`) for any later view of their offers."""

    rows: tuple[OddsTarget, ...]
    recent: tuple[OddsTarget, ...]
    upcoming: tuple[OddsTarget, ...]
    by_state: dict[str, int]
    last_change_utc: str | None
    odds_max_age: timedelta | None
    sport: str | None = None
    snapshots: dict[int, Any] = field(default_factory=dict, repr=False)

    def count(self, *states: str) -> int:
        return sum(self.by_state.get(s, 0) for s in states)

    @property
    def open_count(self) -> int:
        """Targets whose latest state is not final (storage.ODDS_TARGET_FINAL_STATES)."""
        from ..storage import ODDS_TARGET_FINAL_STATES

        return sum(n for s, n in self.by_state.items() if s not in ODDS_TARGET_FINAL_STATES)


# Parsed captures by (snapshot id, payload sha256, receipt time, odds format). Stored snapshots are
# immutable, so an entry can never go stale; the size is bounded (least recently used out first).
_PARSED: "OrderedDict[tuple, Any]" = OrderedDict()


def _parse_capture(row: Any, fallback_format: str) -> Any:
    """A stored odds response parsed by the canonical parser, memoized (raises on an unreadable payload)."""
    from .. import odds_api

    payload = json.loads(row["payload_json"])
    request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
    fmt = request.get("odds_format", fallback_format)
    key = (int(row["id"]), row["payload_sha256"], row["fetched_at_utc"], fmt)
    if key in _PARSED:
        _PARSED.move_to_end(key)
        return _PARSED[key]
    parsed = odds_api.parse_odds(payload.get("events"), odds_format=fmt, received_at_utc=row["fetched_at_utc"],
                                 evidence_id=str(row["id"]))
    _PARSED[key] = parsed
    while len(_PARSED) > ODDS_PARSE_CACHE_MAX:
        _PARSED.popitem(last=False)
    return parsed


def _problems_note(n: Any) -> str | None:
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        return None
    return f"the stored response had {n} parse problem{'' if n == 1 else 's'}; the count may be incomplete"


def _target_times(r: dict[str, Any], now: datetime, cfg: Any) -> tuple[str | None, str | None, bool | None]:
    """(effective due, deadline, expired) by the canonical planner; unknown when a time is unreadable."""
    from .. import odds_schedule

    commence, intended = parse_utc(r.get("commence_time_utc")), parse_utc(r.get("target_utc"))
    if commence is None or intended is None:
        return None, None, None
    try:
        target = odds_schedule.CaptureTarget(
            str(r["target_id"]), str(r["sport"]), str(r["event_id"]), str(r["offset_label"]), int(r["priority"]),
            commence.astimezone(timezone.utc), intended.astimezone(timezone.utc), r.get("home_team"),
            r.get("away_team"))
        return (odds_schedule.iso_z(odds_schedule.effective_due(target, cfg)),
                odds_schedule.iso_z(odds_schedule.deadline(target, cfg)), odds_schedule.is_expired(target, now, cfg))
    except Exception:  # noqa: BLE001 - never guessed
        return None, None, None


def _recorded_books(t: OddsTarget) -> OddsTarget:
    """A history row's books as the runner recorded them at capture (no payload is parsed)."""
    books, offers = t.detail.get("bookmakers"), t.detail.get("offers")
    if not isinstance(books, list) or not all(isinstance(b, str) for b in books):
        return replace(t, books_note="not recorded at capture (the response is parsed only for the rows shown)")
    note = ("this event was not in the stored response (recorded at capture)"
            if t.detail.get("event_present") is False else None)
    return replace(t, books=tuple(books), offers=offers if isinstance(offers, int) and not isinstance(offers, bool)
                   else None, books_source=BOOKS_RECORDED,
                   books_note=" · ".join(x for x in (note, _problems_note(t.detail.get("parse_problems"))) if x) or None)


def _parsed_books(t: OddsTarget, parsed: Any, received: Any) -> OddsTarget:
    """A shown row's books and freshness at receipt, from its parsed capture."""
    from .. import odds_api
    from ..freshness import combine

    eid = odds_api.event_id(t.event_id)
    mine = [o for o in parsed.offers if o.event_id == eid]
    notes = []
    if not any(e.event_id == eid for e in parsed.events):
        notes.append("this event is not in the stored response")
    if parsed.problems:
        notes.append(_problems_note(len(parsed.problems)))
    at = parse_utc(received)
    fresh = (combine(*(odds_api.offer_freshness(o, now=at) for o in mine)).value.upper()
             if mine and at is not None else "UNKNOWN")
    return replace(t, books=tuple(sorted({o.bookmaker for o in mine})), offers=len(mine), books_source=BOOKS_PARSED,
                   books_note=" · ".join(n for n in notes if n) or None, freshness=fresh)


def odds_capture_targets(ctx: Context) -> Loaded:
    """Read-only view of the pilot's `odds_capture_targets` / `odds_capture_transitions` rows for the
    pilot's sport (`odds_pilot.RunnerSettings().sport`).

    NO_DATA when no evidence database is configured or present (the source is unavailable), ERROR
    when it cannot be read (never an empty schedule), OK otherwise, possibly with no rows. Only the
    captures behind the rows shown are loaded and parsed (memoized); a captured response that cannot
    be parsed marks only its own row's books unknown."""
    from .. import odds_api, odds_pilot
    from ..sources import get_source
    from ..storage import ODDS_TARGET_FINAL_STATES, ODDS_TARGET_STATES

    if ctx.store.status != OK:
        return ctx.store
    store = ctx.store.value
    settings = odds_pilot.RunnerSettings()
    try:
        stored = [dict(r) for r in store.odds_targets(sport=settings.sport)]
        spec = get_source(odds_api.SOURCE_ID)
    except Exception as exc:  # noqa: BLE001 - shown as an error state, never as an empty schedule
        return Loaded(ERROR, message=short_error(exc, ctx.config))
    max_age = spec.max_age.get("odds")
    shared: dict[int, int] = {}
    for r in stored:
        if r.get("state") == "CAPTURED" and r.get("snapshot_id") is not None:
            shared[int(r["snapshot_id"])] = shared.get(int(r["snapshot_id"]), 0) + 1

    rows: list[OddsTarget] = []
    for r in stored:
        try:
            detail = json.loads(r.get("detail_json") or "{}")
        except ValueError:
            detail = {"detail_json": "unreadable"}
        state = str(r.get("state"))
        due, deadline, expired = _target_times(r, ctx.now, settings.config)
        sid = int(r["snapshot_id"]) if r.get("snapshot_id") is not None else None
        if state == "CAPTURED":
            fresh = NOT_EVALUATED
        elif state in ODDS_TARGET_FINAL_STATES:
            fresh = TARGET_NO_CAPTURE
        elif state in ODDS_TARGET_STATES and expired is not None:
            fresh = TARGET_OVERDUE if expired else TARGET_PENDING
        else:
            fresh = "UNKNOWN"
        t = OddsTarget(
            target_id=str(r["target_id"]), sport=str(r["sport"]), event_id=str(r["event_id"]),
            offset_label=str(r["offset_label"]), priority=r.get("priority"), home_team=r.get("home_team"),
            away_team=r.get("away_team"), commence_utc=r.get("commence_time_utc"), target_utc=r.get("target_utc"),
            planned_at_utc=r.get("planned_at_utc"), policy_version=r.get("policy_version"), state=state,
            state_at_utc=r.get("state_at_utc"), reason=scrub_paths(r.get("reason"), ctx.config),
            slot_id=r.get("slot_id"), snapshot_id=sid, captured_at_utc=r.get("captured_at_utc"),
            credits_last=r.get("credits_last"), detail=detail if isinstance(detail, dict) else {},
            due_utc=due, deadline_utc=deadline, freshness=fresh,
            shared_targets=shared.get(sid) if state == "CAPTURED" and sid is not None else None)
        rows.append(_recorded_books(t) if state == "CAPTURED" else t)

    def when(t: OddsTarget) -> datetime | None:
        return parse_utc(t.target_utc)
    past = [t for t in rows if (w := when(t)) is not None and w <= ctx.now]
    ahead = [t for t in rows if (w := when(t)) is None or w > ctx.now]  # an unreadable time is never hidden
    shown = [*past[-ODDS_TARGETS_SHOWN:], *ahead[:ODDS_TARGETS_SHOWN]]
    wanted = {t.snapshot_id for t in shown if t.state == "CAPTURED" and t.snapshot_id is not None}
    parsed: dict[int, Any] = {}
    problems: dict[int, str] = {}
    try:
        history = {t.target_id: tuple(dict(x) for x in store.odds_transitions(t.target_id)) for t in shown}
        snaps = store.snapshots_by_id(wanted)
    except Exception as exc:  # noqa: BLE001
        return Loaded(ERROR, message=short_error(exc, ctx.config))
    for sid, snap in snaps.items():
        if snap["source"] != spec.legacy_name or snap["kind"] != "odds":
            problems[sid] = f"snapshot {sid} is not a stored odds response"
            continue
        try:
            parsed[sid] = _parse_capture(snap, settings.odds_format)
        except Exception as exc:  # noqa: BLE001 - one unreadable capture never hides the table
            problems[sid] = f"snapshot {sid} unreadable: {short_error(exc, ctx.config)}"

    def detailed(t: OddsTarget) -> OddsTarget:
        t = replace(t, transitions=history[t.target_id])
        if t.state != "CAPTURED":
            return t
        t = replace(t, consensus=odds_consensus_at_capture(ctx, t.event_id, t.captured_at_utc))
        if t.snapshot_id in parsed:
            return _parsed_books(t, parsed[t.snapshot_id], t.captured_at_utc)
        why = ("no snapshot recorded" if t.snapshot_id is None else
               problems.get(t.snapshot_id, f"snapshot {t.snapshot_id} not found in the evidence database"))
        return replace(t, books=None, offers=None, books_source=None, books_note=why, freshness="UNKNOWN")
    shown_ids = {t.target_id for t in shown}
    rows = [detailed(t) if t.target_id in shown_ids else t for t in rows]
    by_id = {t.target_id: t for t in rows}
    by_state: dict[str, int] = {}
    for t in rows:
        by_state[t.state] = by_state.get(t.state, 0) + 1
    changes = [p for t in rows if (p := parse_utc(t.state_at_utc)) is not None]
    return Loaded(OK, OddsTargets(
        rows=tuple(rows), recent=tuple(by_id[t.target_id] for t in past[-ODDS_TARGETS_SHOWN:][::-1]),
        upcoming=tuple(by_id[t.target_id] for t in ahead[:ODDS_TARGETS_SHOWN]), by_state=by_state,
        last_change_utc=max(changes).astimezone(timezone.utc).isoformat() if changes else None,
        odds_max_age=max_age, sport=settings.sport, snapshots=parsed))


# --------------------------------------------------------------------------- sportsbook consensus (odds_consensus, ADR 0033)

ODDS_CONSENSUS_MODULE = "edge_lab.odds_consensus"
ODDS_CONSENSUS_CACHE_MAX = 64
# Results by (database, event, as_of, newest stored odds snapshot id received at or before as_of): a
# point-in-time read uses only odds snapshots received by as_of, and ids only grow, so any row that
# could change the result changes the key; other sources' writes (every few minutes) never do.
_CONSENSUS: "OrderedDict[tuple, Any]" = OrderedDict()


def _odds_receipts(ctx: Context) -> list[tuple[datetime, int]]:
    """(receipt instant, id) of every stored odds snapshot with a readable receipt time, read once per
    request without loading any payload. The evidence store has no public metadata-only read, so this
    uses the store's own read-only connection (`mode=ro`, `query_only`), as `odds_consensus` does."""
    from contextlib import closing

    from ..odds_consensus import KIND, SOURCE

    cached = ctx.__dict__.get("_odds_receipts")
    if cached is None:
        with closing(ctx.store.value._connect()) as conn:
            rows = conn.execute("SELECT id, fetched_at_utc FROM snapshots WHERE source = ? AND kind = ?",
                                (SOURCE, KIND)).fetchall()
        cached = ctx.__dict__["_odds_receipts"] = [(p, int(r[0])) for r in rows if (p := parse_utc(r[1])) is not None]
    return cached


def _newest_odds_by(ctx: Context, at: datetime) -> int | None:
    return max((sid for received, sid in _odds_receipts(ctx) if received <= at), default=None)


def odds_consensus_at_capture(ctx: Context, event_id: str, received_utc: Any) -> Loaded:
    """Lane C's research benchmark for one event as of one capture's receipt time:
    `odds_consensus.consensus_for_event(store, event_id, as_of=receipt)` (the latest usable stored
    observation of the event known then; newer unusable ones listed). OK carries the
    `SnapshotConsensus` or None (nothing holding the event was known by then); NO_DATA when the
    evidence database or the contract is unavailable, or the receipt time is unknown; ERROR on a read
    failure. Called only for the captured rows a page shows (each call parses one event of one
    snapshot, plus newer unusable ones), and memoized until an odds snapshot received by `as_of` is
    added. Nothing here computes a probability."""
    import importlib

    if ctx.store.status != OK:
        return ctx.store
    as_of = parse_utc(received_utc)
    if as_of is None:
        return Loaded(NO_DATA, message="the capture's receipt time is not recorded, so no point-in-time consensus "
                                       "can be read")
    try:
        module = importlib.import_module(ODDS_CONSENSUS_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != ODDS_CONSENSUS_MODULE:
            return Loaded(ERROR, message=short_error(exc, ctx.config))
        return Loaded(NO_DATA, message="the consensus research benchmark (odds_consensus) is not installed in this "
                                       "build")
    except Exception as exc:  # noqa: BLE001 - a module that fails to import is broken, not absent
        return Loaded(ERROR, message=short_error(exc, ctx.config))
    store, at = ctx.store.value, as_of.astimezone(timezone.utc)
    try:
        key = (str(store.path), str(event_id), at.isoformat(), _newest_odds_by(ctx, at))
        if key in _CONSENSUS:
            _CONSENSUS.move_to_end(key)
            return Loaded(OK, _CONSENSUS[key])
        result = module.consensus_for_event(store, str(event_id), at)
    except Exception as exc:  # noqa: BLE001 - shown as an error state on this row only
        return Loaded(ERROR, message=short_error(exc, ctx.config))
    _CONSENSUS[key] = result
    while len(_CONSENSUS) > ODDS_CONSENSUS_CACHE_MAX:
        _CONSENSUS.popitem(last=False)
    return Loaded(OK, result)


# --------------------------------------------------------------------------- Freshness Fabric (freshness_fabric, ADR 0031)


@dataclass(frozen=True)
class FreshnessReport:
    """The supervisor's artifact as written, plus how old the artifact itself is: `report_freshness`
    is `freshness.assess(generated_at_utc, max_age=freshness_fabric.SUPERVISOR_MAX_AGE, now)`. Every
    source figure stays the artifact's own (as of its generation); nothing is re-derived here."""

    doc: dict[str, Any]
    report_freshness: str  # FRESH | STALE | UNKNOWN
    max_age: timedelta


def report_from_doc(doc: dict[str, Any], now: datetime) -> FreshnessReport:
    """A report and its own age: `freshness.assess(generated_at_utc, SUPERVISOR_MAX_AGE, now)`."""
    from .. import freshness_fabric as ff

    generated = doc.get("generated_at_utc") if isinstance(doc.get("generated_at_utc"), str) else None
    fresh = assess_freshness(generated, max_age=ff.SUPERVISOR_MAX_AGE, now=now).value.upper()
    return FreshnessReport(doc, fresh, ff.SUPERVISOR_MAX_AGE)


def freshness_report(ctx: Context) -> Loaded:
    """The supervisor's artifact, read with the writer's own size bound (a larger file is not its)."""
    from .. import freshness_fabric as ff

    directory = ctx.config.status_dir
    try:
        path = directory / FRESHNESS_FILE if directory is not None else None
        if path is not None and path.is_file() and path.stat().st_size > ff.MAX_ARTIFACT_BYTES:
            return Loaded(ERROR, message=f"{FRESHNESS_FILE} is larger than the supervisor's {ff.MAX_ARTIFACT_BYTES}-byte "
                                         "bound, so it is not its report")
    except OSError as exc:
        return Loaded(ERROR, message=f"{FRESHNESS_FILE} cannot be read: {short_error(exc, ctx.config)}")
    loaded = ctx._status_file(FRESHNESS_FILE)
    if loaded.status == NO_DATA:
        if ctx.config.status_dir is None:
            return loaded
        return Loaded(NO_DATA, message=f"The Freshness Fabric supervisor (edgelab-freshness.timer) has not written "
                                       f"{FRESHNESS_FILE} to the status directory yet")
    if loaded.status != OK:
        return loaded
    doc = loaded.value
    if doc.get("schema") != ff.SCHEMA:
        return Loaded(ERROR, message=f"{FRESHNESS_FILE} has schema {str(doc.get('schema'))[:60]!r}, not {ff.SCHEMA}")
    if not isinstance(doc.get("sources"), list) or not isinstance(doc.get("supervisor"), dict):
        return Loaded(ERROR, message=f"{FRESHNESS_FILE} lacks its sources or supervisor section")
    return Loaded(OK, report_from_doc(doc, ctx.now))


# --------------------------------------------------------------------------- Polymarket US NFL pilot (polymarket_sports, ADR 0032)

PM_SPORTS_MODULE = "edge_lab.polymarket_sports"
PM_EVENTS_SHOWN = 6  # events shown as rows; every event is in the "All events" table


def pm_sports_view(ctx: Context) -> Loaded:
    """Lane B's read-only Terminal view: `polymarket_sports.terminal_view(db, now=...)` (schema
    pm-sports-status/1; network-free; never raises). OK carries the view as returned; NO_DATA when no
    evidence database is configured or present, or the pilot is not installed; ERROR when the view
    says the store or its reading failed. Free text is scrubbed of paths; nothing is recomputed."""
    import importlib

    if ctx.config.db is None:
        return Loaded(NO_DATA, message="no evidence database configured (--db)")
    try:
        module = importlib.import_module(PM_SPORTS_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != PM_SPORTS_MODULE:
            return Loaded(ERROR, message=short_error(exc, ctx.config))
        return Loaded(NO_DATA, message="the Polymarket US NFL pilot (polymarket_sports) is not installed in this build")
    except Exception as exc:  # noqa: BLE001
        return Loaded(ERROR, message=short_error(exc, ctx.config))
    try:
        view = module.terminal_view(ctx.config.db, now=ctx.now)
    except Exception as exc:  # noqa: BLE001 - the contract never raises; anything else is shown
        return Loaded(ERROR, message=short_error(exc, ctx.config))
    if not isinstance(view, dict):
        return Loaded(ERROR, message="the Polymarket US view is not a mapping")
    state = view.get("state")
    detail = scrub_paths(str(view.get("detail") or ""), ctx.config)
    if state == "NO_STORE":
        return Loaded(NO_DATA, message=f"evidence database not readable here ({detail or 'missing'})")
    if state == "ERROR":
        return Loaded(ERROR, message=detail or "the Polymarket US view could not be read")
    return Loaded(OK, view)


def pm_market_history(ctx: Context, slugs: Any) -> Loaded:
    """`polymarket_sports.market_history` (every target and attempt) for the markets a page shows only:
    OK with slug -> list; the capture states (captured, missed, failed, not executable, skipped) come
    from here. Bounded by the caller; read-only."""
    from .. import polymarket_sports

    if ctx.store.status != OK:
        return ctx.store
    try:
        out = {s: [dict(t) for t in polymarket_sports.market_history(ctx.store.value, s)] for s in slugs}
    except Exception as exc:  # noqa: BLE001
        return Loaded(ERROR, message=short_error(exc, ctx.config))
    # The pilot's own rule (`polymarket_sports.status`): an open (planned or failed) target past its
    # deadline is OVERDUE, never still "planned". Kept as `display_state`; `state` stays as recorded.
    for targets in out.values():
        for t in targets:
            deadline = parse_utc(t.get("deadline_utc"))
            if t.get("state") in ("PLANNED", "FAILED") and deadline is not None and deadline < ctx.now:
                t["display_state"] = "OVERDUE"
    return Loaded(OK, out)


# --------------------------------------------------------------------------- Economic Evidence v1 (two research families)

SPORTS_EVIDENCE_MODULE = "edge_lab.sports_evidence"
PAYOFF_EVIDENCE_MODULE = "edge_lab.payoff_constraints"  # Writer 1's PR B evaluator (absent until it lands)


def _optional_module(name: str, absent: str, ctx: Context) -> tuple[Any, Loaded | None]:
    import importlib

    try:
        return importlib.import_module(name), None
    except ModuleNotFoundError as exc:
        if exc.name != name:
            return None, Loaded(ERROR, message=short_error(exc, ctx.config))
        return None, Loaded(NO_DATA, message=absent)
    except Exception as exc:  # noqa: BLE001 - a module that fails to import is broken, not absent
        return None, Loaded(ERROR, message=short_error(exc, ctx.config))


def economic_evidence_a(ctx: Context) -> Loaded:
    """Family A (sportsbook consensus vs Kalshi NFL moneyline): `sports_evidence.terminal_view(db, now=...)`,
    read-only, network-free, memoized by the contract until the evidence or the due set changes. OK carries
    the family view as returned; NO_DATA when no evidence database is configured or readable; ERROR when the
    view reports a failure. Free text is scrubbed of paths; nothing is recomputed here."""
    if ctx.config.db is None:
        return Loaded(NO_DATA, message="no evidence database configured (--db)")
    module, missing = _optional_module(SPORTS_EVIDENCE_MODULE, "the paired-evidence report (sports_evidence) is not "
                                                               "installed in this build", ctx)
    if missing is not None:
        return missing
    try:
        view = module.terminal_view(ctx.config.db, now=ctx.now, experiments_root=ctx.config.experiments_root)
    except Exception as exc:  # noqa: BLE001 - the contract never raises; anything else is shown
        return Loaded(ERROR, message=short_error(exc, ctx.config))
    if not isinstance(view, dict):
        return Loaded(ERROR, message="the paired-evidence view is not a mapping")
    detail = scrub_paths(str(view.get("detail") or ""), ctx.config)
    if view.get("state") == "NO_STORE":
        return Loaded(NO_DATA, message=f"evidence database not readable here ({detail or 'missing'})")
    if view.get("state") != "OK" or not isinstance(view.get("family_a"), dict):
        return Loaded(ERROR, message=detail or "the paired-evidence view could not be read")
    return Loaded(OK, view["family_a"])


def economic_evidence_b(ctx: Context) -> Loaded:
    """Family B (same-venue payoff consistency): the evaluator's own `terminal_view(db, now=...)` once PR B
    installs it; until then NO_DATA saying so. No payoff figure is ever made up here."""
    module, missing = _optional_module(PAYOFF_EVIDENCE_MODULE, "the same-venue payoff evaluator (payoff_constraints, "
                                                               "PR B) is not in this build", ctx)
    if missing is not None:
        return missing
    fn = getattr(module, "terminal_view", None)
    if not callable(fn):
        return Loaded(NO_DATA, message="the payoff evaluator is installed without a Terminal view")
    if ctx.config.db is None:
        return Loaded(NO_DATA, message="no evidence database configured (--db)")
    try:
        view = fn(ctx.config.db, now=ctx.now)
    except Exception as exc:  # noqa: BLE001
        return Loaded(ERROR, message=short_error(exc, ctx.config))
    if not isinstance(view, dict):
        return Loaded(ERROR, message="the payoff evaluator's view is not a mapping")
    return Loaded(OK, view)
