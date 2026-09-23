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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import cached_property
from pathlib import Path
from typing import Any, Callable

from .. import exp001_shadow, experiments as registry, fee_schedules, forward, risk
from ..freshness import Freshness, assess as assess_freshness, parse_utc
from ..outcome_board import build_board
from ..shadow_ledger import AccountState, LedgerError, ShadowLedger
from ..storage import ReadOnlyStoreError, SnapshotStore

OK, NO_DATA, ERROR = "OK", "NO_DATA", "ERROR"
STATUS_MAX_AGE = timedelta(hours=26)
STATUS_FILE_MAX_BYTES = 2_000_000
COLLECTOR_STATUS_FILE = "latest.json"
RECEIPT_FILE = "shadow_daily.json"
FAILURE_FILE = "last_failure.json"
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
    demo: bool = False
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))

    def paths(self) -> list[Path]:
        return [p for p in (self.db, self.ledger, self.status_dir, self.experiments_root) if p is not None]


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
    text = str(exc).splitlines()[0] if str(exc) else ""
    for p in (config.paths() if config else []):
        for variant in {str(p), str(p.resolve())}:
            text = text.replace(variant, p.name)
    text = _ABS_PATH.sub(lambda m: re.split(r"[\\/]", m.group(0).rstrip("\\/"))[-1], text)
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
            fees_verified=fee_verified(), owner_policy_approved=False))

    def _board(self, view: AccountView) -> Loaded:
        try:
            return Loaded(OK, build_board(view.state, self.now, include_settled=True))
        except ValueError as exc:
            return Loaded(ERROR, message=short_error(exc, self.config))

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
                out.append({"key": key, "id": exp.id, "title": exp.data.get("title"), "status": exp.status,
                            "problems": problems.get(key, []), "stage_a": _stage_a(path.parent),
                            "reports": _reports(path.parent)})
        except Exception as exc:  # noqa: BLE001
            return Loaded(ERROR, message=short_error(exc, self.config))
        return Loaded(OK, out)


def fee_verified() -> bool:
    return exp001_shadow.stageb.FEE_SCHEDULE.status is fee_schedules.FeeScheduleStatus.VERIFIED


def fee_rows() -> list[dict[str, Any]]:
    active = exp001_shadow.stageb.FEE_SCHEDULE.schedule_id
    return [{"schedule_id": s.schedule_id, "venue": s.venue, "status": s.status.value,
             "claimable": s.status is fee_schedules.FeeScheduleStatus.VERIFIED, "checked_at_utc": s.checked_at_utc,
             "evidence": s.evidence, "active": s.schedule_id == active}
            for s in fee_schedules.FEE_SCHEDULES.values()]


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
