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
    allowed_hosts: tuple[str, ...] = ()  # extra Host names accepted besides loopback (the bound host)
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
