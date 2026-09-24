"""Presentation contract for Market Edge Terminal v1 (docs/design/UI_CONTRACT.md).

Formatting, the plain-language state vocabulary, bounded query parameters and the typed
view models that pages render. This module groups, sorts, filters and formats values that
canonical modules produced (see `data.py`). It never computes a balance, fee, size,
eligibility verdict, settlement outcome or risk capacity of its own.

Every formatter returns plain text (the components escape it) or None for a missing value;
None always renders as the explicit unavailable marker, never as zero.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, urlencode

from ..forward import eastern_offset
from ..freshness import parse_utc
from ..opportunity import Reason

MINUS = "−"

# --------------------------------------------------------------------------- numbers


def dec(value: Any) -> Decimal | None:
    """A finite Decimal, or None for anything missing or unparseable. Never 0 for missing."""
    if value is None or isinstance(value, bool):
        return None
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _places(d: Decimal, minimum: int) -> int:
    """Decimal places needed to show `d` exactly, at least `minimum`."""
    exp = d.normalize().as_tuple().exponent
    return max(minimum, -exp if isinstance(exp, int) and exp < 0 else 0)


def _sign(d: Decimal, signed: bool) -> str:
    if d < 0:
        return MINUS
    return "+" if signed and d > 0 else ""


def money(value: Any, *, signed: bool = False) -> str | None:
    """$1,000.00. Extra precision is kept when it is economically meaningful ($0.0158)."""
    d = dec(value)
    if d is None:
        return None
    return f"{_sign(d, signed)}${abs(d):,.{_places(d, 2)}f}"


def cents(value: Any, *, signed: bool = False) -> str | None:
    """A $1-contract price in cents: 0.48 -> 48¢, 0.4825 -> 48.25¢ (never rounded away)."""
    d = dec(value)
    if d is None:
        return None
    c = d * 100
    return f"{_sign(c, signed)}{abs(c):,.{_places(c, 0)}f}¢"


def _toward_zero(d: Decimal, places: int) -> tuple[Decimal, bool]:
    """(d truncated toward zero, whether it was nonzero but truncated to zero)."""
    q = Decimal(1).scaleb(-places)
    t = d.quantize(q, rounding=ROUND_DOWN)
    return t, (t == 0 and d != 0)


def edge_cents(value: Any) -> str | None:
    """Net expected value per $1 contract in cents, e.g. +5.12¢.

    Display rounding is toward zero, so a marginally negative value never looks positive
    and a marginal value never looks larger. A value too small to show is "<0.01¢" with
    its sign. The exact figure is always in Details."""
    d = dec(value)
    if d is None:
        return None
    t, tiny = _toward_zero(d * 100, 2)
    sign = MINUS if d < 0 else "+" if d > 0 else ""
    if tiny:
        return f"{sign}<0.01¢"
    return f"{sign}{abs(t):,.{_places(t, 0)}f}¢"


def percent(value: Any, places: int = 1) -> str | None:
    """A probability 0..1 as 64.0%."""
    d = dec(value)
    if d is None:
        return None
    return f"{d * 100:.{places}f}%"


def pp(value: Any) -> str | None:
    """A probability difference in percentage points: +5.2 pp (never "%")."""
    d = dec(value)
    if d is None:
        return None
    t, tiny = _toward_zero(d * 100, 1)
    sign = MINUS if d < 0 else "+" if d > 0 else ""
    return f"{sign}<0.1 pp" if tiny else f"{sign}{abs(t):.1f} pp"


def pp_size(value: Any) -> str | None:
    """An unsigned probability spread (a range or a deviation) in percentage points: 2.1 pp."""
    d = dec(value)
    if d is None:
        return None
    t, tiny = _toward_zero(abs(d) * 100, 1)
    return "<0.1 pp" if tiny else f"{t:.1f} pp"


def count(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return None


def quantity(value: Any) -> str | None:
    d = dec(value)
    if d is None:
        return None
    return f"{d:,.{_places(d, 0)}f}"


# --------------------------------------------------------------------------- times (America/New_York)


def to_et(ts: Any) -> datetime | None:
    """A UTC instant in New York local time via the canonical `forward.eastern_offset`."""
    parsed = parse_utc(ts) if not isinstance(ts, datetime) else (ts if ts.tzinfo else None)
    if parsed is None:
        return None
    parsed = parsed.astimezone(timezone.utc)
    return parsed + eastern_offset(parsed)


def _zone(local: datetime, utc: datetime) -> str:
    return "EDT" if local - utc.replace(tzinfo=None) == timedelta(hours=-4) else "EST"


def _clock(local: datetime) -> str:
    return f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def time_et(ts: Any) -> str | None:
    """5:45 PM EDT."""
    utc = parse_utc(ts) if not isinstance(ts, datetime) else ts
    local = to_et(utc)
    if local is None:
        return None
    return f"{_clock(local)} {_zone(local.replace(tzinfo=None), utc.astimezone(timezone.utc))}"


def date_et(ts: Any, *, year: bool = False) -> str | None:
    """Sep 23 (the New York calendar date)."""
    local = to_et(ts)
    if local is None:
        return None
    return f"{local:%b} {local.day}" + (f", {local.year}" if year else "")


def datetime_et(ts: Any) -> str | None:
    """Sep 23, 5:45 PM EDT."""
    d, t = date_et(ts), time_et(ts)
    return None if d is None or t is None else f"{d}, {t}"


def date_label(value: Any) -> str | None:
    """A calendar date as recorded (YYYY-MM-DD, no time zone): "Sep 23"."""
    try:
        day = datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    return f"{day:%b} {day.day}"


def utc_text(ts: Any) -> str | None:
    """The exact UTC timestamp for Details (as recorded when it is a string)."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.astimezone(timezone.utc).isoformat()
    return str(ts)


def age_text(ts: Any, now: datetime) -> str | None:
    """Supplementary relative age: "11 min ago", "in 3 h". Never the only timestamp shown."""
    parsed = parse_utc(ts) if not isinstance(ts, datetime) else ts
    if parsed is None:
        return None
    seconds = int((now - parsed).total_seconds())
    future, seconds = seconds < 0, abs(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        text = f"{days} d {hours} h" if hours and days < 3 else f"{days} d"
    elif hours:
        text = f"{hours} h {minutes} min" if minutes else f"{hours} h"
    else:
        text = f"{minutes} min"
    return f"in {text}" if future else f"{text} ago"


def hours_text(value: Any) -> str | None:
    d = dec(value)
    if d is None:
        return None
    return f"{d:,.{min(_places(d, 0), 1)}f} h"


# --------------------------------------------------------------------------- state vocabulary

# Semantic kinds: ok (green), err (red), warn (amber), info (blue), nd (neutral).
# Unknown codes are neutral and always keep their original code visible in Details.
OK_K, ERR_K, WARN_K, INFO_K, ND_K = "ok", "err", "warn", "info", "nd"


@dataclass(frozen=True)
class StateWord:
    label: str
    kind: str


STATES: dict[str, StateWord] = {
    # collection and freshness
    "FRESH": StateWord("Fresh", OK_K),
    "STALE": StateWord("Stale", WARN_K),
    "UNKNOWN": StateWord("Unknown", WARN_K),
    "VALID": StateWord("Valid", OK_K),
    "INVALID": StateWord("Capture incomplete", ERR_K),
    "INVALID_CAPTURE": StateWord("Capture incomplete", ERR_K),
    "MISSING_CAPTURE": StateWord("Capture missed", ERR_K),
    "NO_CAPTURE": StateWord("No capture", WARN_K),
    "NOT_CLOSED": StateWord("Window open", WARN_K),
    "LOCK_BUSY": StateWord("Lock busy", ERR_K),
    "ok": StateWord("OK", OK_K),
    "OK": StateWord("OK", OK_K),
    "failed": StateWord("Failed", ERR_K),
    "FAILED": StateWord("Failed", ERR_K),
    "ERROR": StateWord("Error", ERR_K),
    "partial": StateWord("Partial", WARN_K),
    "not_run": StateWord("Not run", WARN_K),
    "overdue": StateWord("Overdue", ERR_K),
    # pipeline receipt
    "HEALTHY_NO_SIGNAL": StateWord("Healthy · no signal", OK_K),
    "HEALTHY_TRADED": StateWord("Healthy · traded", OK_K),
    "PENDING_SETTLEMENT": StateWord("Settlement pending", WARN_K),
    "SETTLEMENT_CONFLICT": StateWord("Settlement conflict", ERR_K),
    # decisions and fills
    "QUALIFY": StateWord("Qualified", OK_K),
    "REJECT": StateWord("Not qualified", ND_K),
    "FILLED": StateWord("Filled (simulated)", OK_K),
    "NO_FILL": StateWord("No fill", WARN_K),
    "RISK_VETO": StateWord("Risk veto", WARN_K),
    "RESEARCH_INVALID_CASH": StateWord("Frozen-rule deviation", ERR_K),
    "CONFIRMATION_MISSING": StateWord("Confirmation missing", WARN_K),
    "SETTLED": StateWord("Settled", OK_K),
    "OPEN": StateWord("Open", INFO_K),
    "PARTIALLY_SETTLED": StateWord("Partly settled", WARN_K),
    # engine reasons (opportunity.Reason)
    "MODEL_UNAVAILABLE": StateWord("No model for this market", WARN_K),
    "EVENT_MISMATCH": StateWord("Event mismatch", ERR_K),
    "EVIDENCE_INCOMPLETE": StateWord("Evidence incomplete", WARN_K),
    "MARKET_CLOSED": StateWord("Market closed", ND_K),
    "RULES_UNRESOLVED": StateWord("Rules not verified", WARN_K),
    "PAYOFF_UNSUPPORTED": StateWord("Payoff not supported", WARN_K),
    "BOOK_MISSING": StateWord("No book captured", WARN_K),
    "BOOK_STALE": StateWord("Stale quote — not actionable", WARN_K),
    "MODEL_STALE": StateWord("Model input stale", WARN_K),
    "INVALID_PRICE": StateWord("Invalid book", ERR_K),
    "INSUFFICIENT_SIZE": StateWord("Insufficient size", WARN_K),
    "FEE_UNVERIFIED": StateWord("Fees unverified", WARN_K),
    "FEE_UNSUPPORTED": StateWord("No fee model", WARN_K),
    "NO_EDGE": StateWord("Edge below threshold", ND_K),
    # risk and policy
    "BREACH": StateWord("Limit breached", ERR_K),
    "HALTED": StateWord("New positions halted", ERR_K),
    "ELIGIBLE": StateWord("Within starter horizon", OK_K),
    "STARTER_POLICY_INELIGIBLE": StateWord("Outside starter horizon", WARN_K),
    "HORIZON_OVER_7D": StateWord("Outside starter horizon", WARN_K),
    "TRADABLE_CASH_RELEASE_UNKNOWN": StateWord("Cash release unknown", WARN_K),
    "SETTLEMENT_TIMING_UNVERIFIED": StateWord("Settlement timing unverified", WARN_K),
    "POST_SETTLEMENT_HOLD": StateWord("Post-settlement hold", WARN_K),
    "DELAYED_OR_DISPUTED": StateWord("Delayed or disputed", WARN_K),
    "EXIT_DEPENDS_ON_LIQUIDITY": StateWord("Exit depends on liquidity", WARN_K),
    "SEVEN_DAY_POLICY_EXCEPTION": StateWord("Starter-policy exception", ERR_K),
    "NOT_RECOMMENDED": StateWord("Not enabled", ERR_K),
    # fees
    "UNVERIFIED_CURRENT_SCHEDULE": StateWord("Fees unverified", ERR_K),
    "UNVERIFIED": StateWord("Unverified", ERR_K),
    "PARTIALLY_VERIFIED": StateWord("Partly verified", WARN_K),
    "VERIFIED": StateWord("Verified", OK_K),
    "EXACT": StateWord("Exact", OK_K),
    "CONSERVATIVE_BOUND": StateWord("Conservative bound", WARN_K),
    "OWNER_ATTESTED": StateWord("Owner-attested", WARN_K),
    "NONE": StateWord("No claim basis", ERR_K),
    "UNSUPPORTED": StateWord("Unsupported", ERR_K),
    # venues and sources (venues.ConnectivityStage)
    "LIVE_DATA_VERIFIED": StateWord("Live data verified", OK_K),
    "TESTED": StateWord("Tested (not connected)", WARN_K),
    "IMPLEMENTED": StateWord("Code only", WARN_K),
    "PLANNED": StateWord("Planned", ND_K),
    "NEEDS_ACCESS": StateWord("Access not connected", WARN_K),
    "PARTIAL": StateWord("Partial", WARN_K),
    # experiments
    "RUNNING": StateWord("Running", INFO_K),
    "DRAFT": StateWord("Draft", ND_K),
    "PREREGISTERED": StateWord("Preregistered", INFO_K),
    "PASS": StateWord("Historical validation passed", OK_K),
    "CONCLUDED_PASS": StateWord("Concluded · pass", OK_K),
    "CONCLUDED_FAIL": StateWord("Concluded · fail", ERR_K),
    "FAIL": StateWord("Failed", ERR_K),
    # notifications
    "INFO": StateWord("Info", INFO_K),
    "WARNING": StateWord("Warning", WARN_K),
    "CRITICAL": StateWord("Critical", ERR_K),
    # generic data states
    "NO_DATA": StateWord("Waiting for first capture", ND_K),
    "NOT_STARTED": StateWord("Not started", ND_K),
    "NOT_EVALUATED": StateWord("Not evaluated yet", ND_K),
    "HISTORICAL": StateWord("Historical decision", ND_K),
    "CAPTURE_INCOMPLETE": StateWord("Capture incomplete", WARN_K),
    "UNAVAILABLE": StateWord("Unavailable", ND_K),
    "EXPIRED": StateWord("Expired", ND_K),
    "MALFORMED": StateWord("Malformed", ERR_K),
    # across venues (best_price comparator, ADR 0027): equivalence, depth and route exclusions
    "REFERENCE": StateWord("This market (reference)", INFO_K),
    "MATCHED_EQUIVALENT": StateWord("Rules equivalent", OK_K),
    "RELATED_NOT_EQUIVALENT": StateWord("RELATED MARKET — NOT ECONOMICALLY EQUIVALENT", WARN_K),
    "FILLABLE": StateWord("Fillable for the size", OK_K),
    "INSUFFICIENT_DEPTH": StateWord("Insufficient depth", WARN_K),
    "DEPTH_UNKNOWN": StateWord("Depth unknown (truncated book)", WARN_K),
    "INVALID_BOOK": StateWord("Invalid book", ERR_K),
    "NO_OFFER": StateWord("Nothing offered", WARN_K),
    "MARKET_NOT_OPEN": StateWord("Market not open", ND_K),
    "FEE_NOT_PRICED": StateWord("Fee not priced", WARN_K),
    "NOT_FRESH": StateWord("Stale at decision time — not ranked", WARN_K),
    "NO_ACCOUNT_CONNECTED": StateWord("No account connected", WARN_K),
    "CAPITAL_RELEASE_INELIGIBLE": StateWord("Outside starter horizon", WARN_K),
    "NO_EQUIVALENT_ROUTE": StateWord("No equivalent route", ND_K),
    "NO_ELIGIBLE_ROUTE": StateWord("No eligible route", ND_K),
    "ALL_GATES_PASSED": StateWord("Passes every claim gate", OK_K),
    # research sizing verdicts (sizing_v2.Verdict, via sizing_counterfactual.panel_for_market)
    "SIZE": StateWord("Sized (research)", INFO_K),
    "ZERO_EDGE": StateWord("Zero: no edge after costs", ND_K),
    "UNCERTAINTY_TOO_HIGH": StateWord("Zero: uncertainty too high", ND_K),
    "LIQUIDITY_LIMIT": StateWord("Limited by liquidity", WARN_K),
    "RISK_LIMIT": StateWord("Limited by risk caps", WARN_K),
    "STALE_DATA": StateWord("Stale data", WARN_K),
    "CAPITAL_HORIZON": StateWord("Outside capital horizon", WARN_K),
    # notification origin (notifications.Origin, ADR 0020) and delivery by origin
    "ORIGIN_PRODUCTION": StateWord("Production", ERR_K),
    "ORIGIN_TEST": StateWord("Test", ND_K),
    "ORIGIN_DEPLOYMENT_VERIFICATION": StateWord("Verification check", ND_K),
    "ORIGIN_MANUAL_DIAGNOSTIC": StateWord("Manual diagnostic", ND_K),
    "ORIGIN_REPLAY": StateWord("Replay", ND_K),
    "ORIGIN_DEMO": StateWord("Demo", ND_K),
    "ORIGIN_UNKNOWN": StateWord("Origin unrecognised", WARN_K),
    "HELD_BY_ORIGIN": StateWord("Stored, not pushed (origin)", ND_K),
    "VERIFICATION_UNCONFIRMED": StateWord("Verification not confirmed", WARN_K),
    # The Odds API pilot (odds_pilot.dashboard_status, most blocking first). Never "connected"
    # before a stored live read that held offers.
    "COST_BLOCKED": StateWord("Cost blocked", ERR_K),
    "KEY_REJECTED": StateWord("Key rejected", ERR_K),
    "SETUP_NEEDED": StateWord("Setup needed", WARN_K),
    "DEGRADED": StateWord("Degraded", WARN_K),
    "QUOTA_EXHAUSTED": StateWord("Quota exhausted", WARN_K),
    "QUOTA_UNKNOWN": StateWord("Quota unknown", WARN_K),
    "DISCOVERY_FAILED": StateWord("Discovery failed", WARN_K),
    "DISCOVERY_STALE": StateWord("Discovery stale", WARN_K),
    "ACTIVE": StateWord("Active · live read verified", OK_K),
    "PENDING": StateWord("Pending: not yet known", ND_K),
    # The Odds API capture targets (storage.ODDS_TARGET_STATES; PLANNED, FAILED, QUOTA_* and
    # SETUP_NEEDED above keep their words) and one target's freshness (data.odds_capture_targets).
    "CAPTURED": StateWord("Captured", OK_K),
    "CAPTURING": StateWord("Capture in progress", INFO_K),
    "MISSED": StateWord("Missed", ERR_K),
    "SKIPPED_BUDGET": StateWord("Skipped · budget", WARN_K),
    "DEFERRED": StateWord("Deferred", WARN_K),
    "SUPERSEDED": StateWord("Superseded", ND_K),
    "TARGET_OVERDUE": StateWord("Overdue", WARN_K),
    "TARGET_PENDING": StateWord("Not captured yet", ND_K),
    "TARGET_NO_CAPTURE": StateWord("Nothing captured", ND_K),
    # Sportsbook consensus proposition status (odds_consensus.ConsensusStatus); research only, never green.
    "CONSENSUS_SUPPORTED": StateWord("Consensus computed", INFO_K),
    "CONSENSUS_INSUFFICIENT_BOOKS": StateWord("Insufficient books", WARN_K),
    "CONSENSUS_UNSUPPORTED": StateWord("Unsupported", WARN_K),
}


def state_word(code: Any) -> StateWord:
    """The plain-language word for a stored code. Unknown codes are neutral, never green."""
    if code is None:
        return StateWord("Unknown", WARN_K)
    text = str(code)
    return STATES.get(text, StateWord(text.replace("_", " ").capitalize() if text.isupper() else text, ND_K))


# Engine reasons that block a market for reasons other than price: evidence, rules, book,
# model or fee problems. NO_EDGE alone means the market was observed and not qualified.
BLOCKING_REASONS = frozenset(r.value for r in Reason if r not in (Reason.QUALIFY, Reason.NO_EDGE))
BLOCKING_FILLS = frozenset({"RISK_VETO", "STARTER_POLICY_INELIGIBLE", "RESEARCH_INVALID_CASH"})


# --------------------------------------------------------------------------- query parameters

DOMAINS = (("all", "All"), ("weather", "Weather"), ("sports", "Sports"), ("politics", "Politics"),
           ("economics", "Economics"), ("financial", "Financial"), ("other", "Other"))
DOMAIN_KEYS = {k for k, _ in DOMAINS}
BOARD_STATES = (("all", "All observed"), ("qualified", "Qualified"), ("watching", "Watching"), ("blocked", "Blocked"))
HORIZONS = (("all", "All"), ("within7", "Within 7 days"), ("over7", "Over 7 days"), ("unknown", "Unknown"))
SORTS = (("default", "Edge, then release"), ("edge", "Net edge"), ("release", "Cash release"),
         ("title", "Market name"))
POSITION_STATES = (("open", "Open"), ("settling", "Settling"), ("closed", "Closed"), ("all", "All"))
RESEARCH_TABS = (("research", "Research"), ("sources", "Data sources"))
ACCOUNT_KEYS = ("operational", "research")
PAGE_SIZE = 25
MAX_PAGE = 1000
MAX_QUERY = 120
MAX_QUERY_STRING = 2048
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]{0,99}")
_VENUE = re.compile(r"[a-z][a-z0-9_]{0,39}")
_SPORT = re.compile(r"[a-z0-9][a-z0-9_\-]{0,39}")

# Which parameters each route accepts. Anything else is ignored (it never reaches a page).
ROUTE_PARAMS: dict[str, frozenset[str]] = {
    "/": frozenset({"account", "state"}),
    "/opportunities": frozenset({"q", "domain", "sport", "venue", "state", "horizon", "sort", "account", "page"}),
    "/positions": frozenset({"account", "state"}),
    "/outcome-board": frozenset({"account"}),
    "/risk": frozenset({"account"}),
    "/experiments": frozenset({"tab"}),
    "/alerts": frozenset(),
    "/more": frozenset(),
    "/market": frozenset({"venue", "id", "side", "account", "q", "domain", "sport", "state", "horizon", "sort",
                          "page"}),
    "/gallery": frozenset(),
}


class ParamError(ValueError):
    """A known parameter with an unsupported value. The message is safe to show."""


@dataclass(frozen=True)
class Params:
    """Validated view state for one request. Defaults describe the unfiltered view."""

    route: str = "/"
    account: str = "operational"
    q: str = ""
    domain: str = "all"
    sport: str = "all"
    venue: str = "all"
    state: str = ""  # route-specific: board state or position state
    horizon: str = "all"
    sort: str = "default"
    page: int = 1
    tab: str = "research"
    market_id: str = ""  # /market: the native id
    side: str = ""

    def board_state(self) -> str:
        return self.state or "all"

    def position_state(self) -> str:
        return self.state or "open"

    def filters(self, **changes: Any) -> dict[str, str]:
        """The Markets filter parameters that differ from the defaults (for links)."""
        p = replace(self, **changes)
        out = {"q": p.q, "domain": p.domain, "sport": p.sport, "venue": p.venue, "state": p.board_state(),
               "horizon": p.horizon, "sort": p.sort, "account": p.account, "page": str(p.page)}
        defaults = {"q": "", "domain": "all", "sport": "all", "venue": "all", "state": "all", "horizon": "all",
                    "sort": "default", "account": "operational", "page": "1"}
        return {k: v for k, v in out.items() if v != defaults[k]}

    def href(self, path: str, **changes: Any) -> str:
        """A same-origin link to `path` that keeps the filters (values URL-encoded)."""
        params = self.filters(**changes)
        return path + ("?" + urlencode(params) if params else "")


def _one(pairs: list[tuple[str, str]], name: str) -> str | None:
    values = [v for k, v in pairs if k == name]
    if len(values) > 1:
        raise ParamError(f"{name} was given more than once")
    return values[0] if values else None


def _choice(value: str | None, allowed: Iterable[str], name: str, default: str) -> str:
    if value is None or value == "":
        return default
    if value not in set(allowed):
        raise ParamError(f"unsupported value for {name}")
    return value


def parse_params(route: str, query_string: str, *, venues: Iterable[str] = (), sports: Iterable[str] = ()) -> Params:
    """Validate the query string against `route`'s allowlist. Raises ParamError (safe text).

    Values are never interpreted as a path, SQL, callable, command or URL: each is checked
    against a fixed set, a registry of known identities, or a bounded character class."""
    allowed = ROUTE_PARAMS.get(route, frozenset())
    if len(query_string) > MAX_QUERY_STRING:
        raise ParamError("the query string is too long")
    try:
        pairs = [(k, v) for k, v in parse_qsl(query_string, keep_blank_values=True, max_num_fields=40)
                 if k in allowed]
    except ValueError:
        raise ParamError("the query string has too many fields") from None
    get = lambda name: _one(pairs, name)  # noqa: E731
    p = Params(route=route)
    changes: dict[str, Any] = {}
    if "account" in allowed:
        changes["account"] = _choice(get("account"), ACCOUNT_KEYS, "account", "operational")
    if "q" in allowed:
        q = (get("q") or "").strip()
        if len(q) > MAX_QUERY:
            raise ParamError(f"search is limited to {MAX_QUERY} characters")
        if any(ord(c) < 32 or ord(c) == 127 for c in q):
            raise ParamError("search contains control characters")
        changes["q"] = q
    if "domain" in allowed:
        changes["domain"] = _choice(get("domain"), DOMAIN_KEYS, "domain", "all")
    if "sport" in allowed:
        sport = get("sport") or "all"
        if sport != "all" and (not _SPORT.fullmatch(sport) or sport not in set(sports)):
            raise ParamError("unsupported value for sport")
        changes["sport"] = sport
    if "venue" in allowed:
        venue = get("venue") or ("" if route == "/market" else "all")
        if venue not in ("", "all") and (not _VENUE.fullmatch(venue) or venue not in set(venues)):
            raise ParamError("unsupported value for venue")
        changes["venue"] = venue
    if "state" in allowed:
        states = POSITION_STATES if route == "/positions" else BOARD_STATES
        changes["state"] = _choice(get("state"), [k for k, _ in states], "state", "")
    if "horizon" in allowed:
        changes["horizon"] = _choice(get("horizon"), [k for k, _ in HORIZONS], "horizon", "all")
    if "sort" in allowed:
        changes["sort"] = _choice(get("sort"), [k for k, _ in SORTS], "sort", "default")
    if "page" in allowed:
        raw = get("page") or "1"
        if not (raw.isascii() and raw.isdigit()) or not 1 <= int(raw) <= MAX_PAGE:
            raise ParamError("unsupported value for page")
        changes["page"] = int(raw)
    if "tab" in allowed:
        changes["tab"] = _choice(get("tab"), [k for k, _ in RESEARCH_TABS], "tab", "research")
    if "id" in allowed:
        mid = get("id") or ""
        if mid and not _ID.fullmatch(mid):
            raise ParamError("unsupported market id")
        changes["market_id"] = mid
    if "side" in allowed:
        changes["side"] = _choice(get("side"), ("YES", "NO"), "side", "")
    return replace(p, **changes)


# --------------------------------------------------------------------------- market board view model

VENUE_LABELS = {"kalshi": "Kalshi", "polymarket_us": "Polymarket US", "polymarket_international": "Polymarket International",
                "novig": "Novig", "odds_api": "The Odds API", "the_odds_api": "The Odds API"}
DOMAIN_LABELS = dict(DOMAINS)


def venue_label(venue: Any) -> str:
    return VENUE_LABELS.get(str(venue), str(venue)) if venue else "Unknown venue"


def domain_of(event_id: Any, fallback: Any = None) -> str:
    """The domain from a normalized event id ("weather:..."), else the fallback, else other."""
    for candidate in (str(event_id or "").split(":", 1)[0], fallback):
        if candidate in DOMAIN_KEYS and candidate != "all":
            return str(candidate)
    return "other"


# Outcome-cluster ids with a known meaning, mapped to plain language. Only patterns listed here
# get a label; anything else is shown as its raw id, never a guessed description.
_CLUSTER_LABELS = (
    # EXP-001 (exp001_stageb): the Central Park daily maximum temperature for one target day.
    (re.compile(r"weather:us-nyc-central-park:([0-9]{4}-[0-9]{2}-[0-9]{2})"), "NYC Central Park high temperature"),
)


def cluster_label(cluster: Any) -> str:
    """A plain-language outcome-cluster label ("NYC Central Park high temperature · Sep 24"), else the raw id."""
    raw = str(cluster) if cluster is not None else ""
    for pattern, label in _CLUSTER_LABELS:
        m = pattern.fullmatch(raw)
        day = date_label(m.group(1)) if m else None
        if day:
            return f"{label} · {day}"
    return raw


@dataclass(frozen=True)
class QuoteSide:
    """The latest captured executable buy price for one side of one market."""

    side: str
    label: str | None  # outcome text for this side
    price: Decimal | None
    size: Decimal | None
    received_at_utc: str | None
    phase: str | None  # which capture it came from ("decision" | "recheck" | "decision payload")
    evidence_id: str | None
    anomaly: str | None
    change: Decimal | None = None  # same side, same field (ask), vs `change_from_utc`; None = unavailable
    change_from_utc: str | None = None
    change_note: str = "Change unavailable: no comparable earlier observation"
    capture_status: str | None = None  # the forward capture's own status ("complete" | "partial" | ...)

    @property
    def capture_complete(self) -> bool:
        return self.capture_status == "complete"


@dataclass(frozen=True)
class Assessment:
    """One recorded decision payload (Gate 5 engine at decision time). Nothing is recomputed."""

    account_id: str
    decision_id: str | None
    decided_at_utc: str | None
    side: str | None
    outcome: str | None
    qualification: str | None
    reason: str | None
    reasons: tuple[str, ...]
    model_probability: Decimal | None
    conservative_probability: Decimal | None
    executable_price: Decimal | None
    displayed_size: Decimal | None
    fee: Decimal | None
    all_in_cost: Decimal | None
    net_edge: Decimal | None
    net_edge_conservative: Decimal | None
    fee_status: str | None
    claim_basis: str | None
    model_id: str | None
    model_version: str | None
    freshness: str | None
    size: Any
    binding_constraint: str | None
    fill_status: str | None
    fill_reason: str | None
    starter: Mapping[str, Any] | None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)
    fill_cost: Decimal | None = None  # the simulated fill's total cost (= maximum loss of a long binary)
    target_date: str | None = None  # the target day the decision was made for (from its slot)


@dataclass(frozen=True)
class MarketRow:
    venue: str
    market_id: str
    native_id: str
    domain: str
    league: str | None
    title: str | None
    outcome: str | None
    target_date: str | None
    status: str | None
    close_time_utc: str | None
    rules_primary: str | None
    payoff_kind: str | None
    event_id: str | None
    quotes: Mapping[str, QuoteSide]  # side -> latest quote
    assessments: tuple[Assessment, ...]  # decisions for this market's current target day (selected account)
    observed: bool  # captured in the evidence store (not only in a decision payload)
    has_position: bool = False
    history: tuple[Assessment, ...] = ()  # decisions recorded for an earlier target day: never current
    historical: bool = False  # the whole row belongs to an earlier target day than the current one
    now: datetime | None = None  # the render time, for overdue labels only

    def for_side(self, side: str | None) -> Assessment | None:
        """The latest current assessment for `side` (detail pages keep every section on one side)."""
        items = [a for a in self.assessments if a.side == side]
        return max(items, key=lambda a: str(a.decided_at_utc)) if items else None

    @property
    def primary(self) -> Assessment | None:
        """The qualified assessment if any, else the one with the larger known net edge, else the latest."""
        if not self.assessments:
            return None
        qualified = [a for a in self.assessments if a.qualification == "QUALIFY"]
        pool = qualified or list(self.assessments)
        known = [a for a in pool if a.net_edge is not None]
        if known:
            return max(known, key=lambda a: (a.net_edge, str(a.decided_at_utc)))
        return max(pool, key=lambda a: str(a.decided_at_utc))

    @property
    def state(self) -> str:
        """qualified | watching | blocked | unsupported | historical (a display grouping of recorded
        verdicts). A decision made for an earlier target day is historical, never "qualified" now."""
        if self.payoff_kind not in (None, "binary"):
            return "unsupported"
        if self.historical:
            return "historical"
        a = self.primary
        if a is None:
            return "watching"
        if a.qualification == "QUALIFY" and a.fill_reason not in BLOCKING_FILLS:
            return "qualified"
        if set(a.reasons) & BLOCKING_REASONS or a.fill_reason in BLOCKING_FILLS:
            return "blocked"
        return "watching"

    @property
    def state_code(self) -> str:
        a = self.primary
        if self.state == "unsupported":
            return "PAYOFF_UNSUPPORTED"
        if self.historical:
            return "HISTORICAL"
        if a is None:
            return "NOT_EVALUATED"
        if a.fill_reason in BLOCKING_FILLS:
            return a.fill_reason
        return a.qualification if a.qualification == "QUALIFY" else (a.reason or "REJECT")

    @property
    def cash_release(self) -> tuple[str, str | None, Any]:
        """(within7 | over7 | unknown, tradable-cash ETA, hours) from the recorded starter verdict."""
        a = self.primary
        verdict = a.starter if a is not None else None
        if not isinstance(verdict, Mapping):
            return "unknown", None, None
        reasons = set(verdict.get("reasons") or ())
        eta = verdict.get("tradable_cash_release_eta_utc")
        hours = verdict.get("elapsed_hours_to_tradable")
        if "HORIZON_OVER_7D" in reasons:
            return "over7", eta, hours
        if eta is not None and verdict.get("eligible") is True and not reasons:
            return "within7", eta, hours
        return "unknown", eta, hours  # missing ETA, or ineligible for another reason (delayed, disputed, ...)

    @property
    def search_text(self) -> str:
        return " ".join(str(x) for x in (self.title, self.outcome, self.native_id, self.market_id,
                                          venue_label(self.venue), DOMAIN_LABELS.get(self.domain), self.league)
                        if x).lower()


def _q(obs: Any) -> Decimal | None:
    return dec(obs)


def _starter(decision: Mapping[str, Any], fill: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    for source in (fill or {}, decision):
        verdict = source.get("starter_policy") if isinstance(source, Mapping) else None
        if isinstance(verdict, Mapping):
            return verdict
    return None


def assessment_from(account_id: str, decision: Mapping[str, Any], fill: Mapping[str, Any] | None) -> Assessment:
    opp = decision.get("opportunity") if isinstance(decision.get("opportunity"), Mapping) else {}
    sizing = decision.get("sizing") if isinstance(decision.get("sizing"), Mapping) else {}
    reasons = decision.get("reasons") if isinstance(decision.get("reasons"), list) else []
    claim = decision.get("claim_basis") or ("NONE" if decision.get("claimable") is False else None)
    return Assessment(
        account_id=account_id, decision_id=decision.get("decision_id"), decided_at_utc=decision.get("as_of_utc"),
        side=decision.get("side"), outcome=opp.get("outcome"), qualification=decision.get("qualification"),
        reason=decision.get("reason"), reasons=tuple(str(r) for r in reasons),
        model_probability=dec(opp.get("model_probability")),
        conservative_probability=dec(opp.get("conservative_probability")),
        executable_price=dec(opp.get("executable_price")), displayed_size=dec(opp.get("displayed_size")),
        fee=dec(opp.get("fee")), all_in_cost=dec(opp.get("all_in_cost")), net_edge=dec(opp.get("net_edge")),
        net_edge_conservative=dec(opp.get("net_edge_conservative")), fee_status=opp.get("fee_status"),
        claim_basis=claim, model_id=opp.get("model_id"), model_version=opp.get("model_version") or
        decision.get("model_version"), freshness=opp.get("freshness"), size=sizing.get("final_size"),
        binding_constraint=sizing.get("binding_constraint"),
        fill_status=(fill or {}).get("status"), fill_reason=(fill or {}).get("reason") if fill else None,
        starter=_starter(decision, fill), raw=decision, fill_cost=dec((fill or {}).get("total_cost")),
        target_date=str(decision.get("slot") or "").split("|")[0] or None)


def _side_label(market: Any, side: str) -> str | None:
    if side == "YES":
        return getattr(market, "outcome", None)
    no = getattr(market, "no_outcome", None)
    return no if no else (f"Not {market.outcome}" if getattr(market, "outcome", None) else None)


def observed_quotes(market: Any, capture_status: Mapping[str, Any] | None = None) -> dict[str, QuoteSide]:
    """Latest quote per side from an ObservedMarket, with change vs the earlier capture of the day.
    `capture_status` maps a phase to its forward capture's status, so quotes from an incomplete
    capture are labelled as such."""
    capture_status = capture_status or {}
    out: dict[str, QuoteSide] = {}
    phases = [p for p in ("decision", "recheck") if p in market.quotes]
    for side in ("YES", "NO"):
        seen = [(p, market.quotes[p].get(side)) for p in phases if market.quotes[p].get(side) is not None]
        if not seen:
            continue
        phase, latest = seen[-1]
        change, since, note = None, None, "Change unavailable: no comparable earlier observation"
        if len(seen) >= 2:
            _, earlier = seen[-2]
            if latest.ask is not None and earlier.ask is not None and not latest.anomaly and not earlier.anomaly:
                change, since = _q(latest.ask) - _q(earlier.ask), earlier.received_at_utc
                note = "Change in the captured ask for this side since the decision capture"
            else:
                note = "Change unavailable: one of the two captures has no valid ask for this side"
        out[side] = QuoteSide(side, _side_label(market, side), _q(latest.ask), _q(latest.size),
                              latest.received_at_utc, phase, latest.evidence_id, latest.anomaly, change, since, note,
                              capture_status.get(phase))
    return out


def _by_time(items: Iterable[Assessment]) -> tuple[Assessment, ...]:
    return tuple(sorted(items, key=lambda a: str(a.decided_at_utc)))


def build_rows(observed: Iterable[Any], account_id: str, decisions: Iterable[Mapping[str, Any]],
               fills: Mapping[str, Mapping[str, Any]], open_market_ids: Iterable[str] = (), *,
               current_target: str | None = None, capture_status: Mapping[str, Any] | None = None,
               now: datetime | None = None) -> list[MarketRow]:
    """Join captured markets (evidence store) with the selected account's recorded decisions.

    Only a decision made for the market's own current target day counts as its assessment; an
    older decision on the same id is kept as history and never makes the row "qualified".
    `current_target` is the captured target day (or, with no captures, the latest decided
    day). A market known only from a decision payload is still shown, its decision-time price
    labelled as such, and it is historical unless it belongs to the current target day.
    Deduplicated by venue plus native market id."""
    open_ids = set(open_market_ids)
    observed = list(observed)
    by_market: dict[str, list[Assessment]] = {}
    meta: dict[str, Mapping[str, Any]] = {}
    for dec_payload in decisions:
        mid = dec_payload.get("market_id")
        if not isinstance(mid, str):
            continue
        by_market.setdefault(mid, []).append(
            assessment_from(account_id, dec_payload, fills.get(dec_payload.get("decision_id"))))
        meta.setdefault(mid, dec_payload)
    # The current target day per domain: the captured day for the observed domain, raised to the
    # latest decided day when decisions are newer (a day whose books were not captured); each other
    # domain uses its own latest decided day. A row is historical only when it is EARLIER.
    domain_now: dict[str, str] = {}
    for mid, items in by_market.items():
        dom = domain_of(meta[mid].get("event_id"))
        for a in items:
            if a.target_date and a.target_date > domain_now.get(dom, ""):
                domain_now[dom] = a.target_date
    for m in observed:
        dom = domain_of(m.event_id, m.domain)
        if current_target and current_target > domain_now.get(dom, ""):
            domain_now[dom] = current_target
    rows: dict[str, MarketRow] = {}
    for m in observed:
        items = by_market.get(m.market_id, [])
        dom = domain_of(m.event_id, m.domain)
        # A captured day older than its domain's newest decided day (a missed capture) is historical too.
        stale_day = bool(m.target_date) and m.target_date < domain_now.get(dom, m.target_date)
        rows[m.market_id] = MarketRow(
            venue=m.venue, market_id=m.market_id, native_id=m.native_id, domain=dom,
            league=None, title=m.title, outcome=m.outcome, target_date=m.target_date, status=m.status,
            close_time_utc=m.close_time_utc, rules_primary=m.rules_primary, payoff_kind=m.payoff_kind,
            event_id=m.event_id, quotes=observed_quotes(m, capture_status),
            assessments=_by_time(a for a in items if a.target_date == m.target_date),
            history=_by_time(a for a in items if a.target_date != m.target_date),
            observed=True, has_position=m.market_id in open_ids, historical=stale_day, now=now)
    for mid, assessments in by_market.items():
        if mid in rows:
            continue
        payload = meta[mid]
        venue, _, native = mid.partition(":")
        latest = max(assessments, key=lambda a: str(a.decided_at_utc))
        quotes = {a.side: QuoteSide(a.side, a.outcome if a.side == "YES" else None, a.executable_price,
                                    a.displayed_size, a.decided_at_utc, "decision payload", None, None)
                  for a in _by_time(assessments) if a.side in ("YES", "NO")}
        domain = domain_of(payload.get("event_id"))
        target = max((a.target_date for a in assessments if a.target_date), default=None)
        current = [a for a in assessments if a.target_date is not None and a.target_date == target]
        historical = target is None or target < domain_now.get(domain, target)
        rows[mid] = MarketRow(
            venue=venue or "unknown", market_id=mid, native_id=native or mid, domain=domain,
            league=None, title=None, outcome=latest.outcome, target_date=target, status=None,
            close_time_utc=None, rules_primary=None, payoff_kind=None, event_id=payload.get("event_id"),
            quotes=quotes, assessments=_by_time(current or assessments),
            history=_by_time(a for a in assessments if a not in current) if current else (),
            observed=False, has_position=mid in open_ids, historical=historical, now=now)
    return list(rows.values())


def _release_key(row: MarketRow) -> tuple:
    _, eta, _ = row.cash_release
    parsed = parse_utc(eta)
    return (0, parsed) if parsed is not None else (1, datetime.max.replace(tzinfo=timezone.utc))


def _title_key(row: MarketRow) -> tuple:
    return (str(row.title or row.outcome or "").lower(), row.market_id)


def sort_rows(rows: Iterable[MarketRow], sort: str = "default") -> list[MarketRow]:
    """Deterministic ordering; unknown values always sort last."""
    rows = list(rows)
    if sort == "title":
        return sorted(rows, key=_title_key)
    if sort == "release":
        return sorted(rows, key=lambda r: (_release_key(r), _title_key(r)))

    def edge_key(r: MarketRow) -> tuple:
        a = r.primary
        e = a.net_edge if a is not None and not r.historical else None
        return (0, -e) if e is not None else (1, Decimal(0))
    if sort == "edge":
        return sorted(rows, key=lambda r: (edge_key(r), _title_key(r)))
    qualified = sorted((r for r in rows if r.state == "qualified"), key=lambda r: (edge_key(r), _title_key(r)))
    rest = sorted((r for r in rows if r.state not in ("qualified", "historical")),
                  key=lambda r: (_release_key(r), _title_key(r)))
    past = sorted((r for r in rows if r.state == "historical"),
                  key=lambda r: (str(r.target_date or ""), r.market_id), reverse=True)
    return qualified + rest + past  # decisions for earlier target days always last


def filter_rows(rows: Iterable[MarketRow], p: Params) -> list[MarketRow]:
    out = []
    q = p.q.lower()
    for r in rows:
        if p.domain != "all" and r.domain != p.domain:
            continue
        if p.sport != "all" and (r.league or "") != p.sport:
            continue
        if p.venue not in ("all", "") and r.venue != p.venue:
            continue
        state = p.board_state()
        if state != "all" and r.state != state:
            continue
        if p.horizon != "all" and r.cash_release[0] != p.horizon:
            continue
        if q and q not in r.search_text:
            continue
        out.append(r)
    return out


def tape_rows(rows: Iterable[MarketRow], limit: int = 12) -> list[tuple[MarketRow, QuoteSide]]:
    """Up to `limit` tape items from actual captured quotes: open-position markets first, then
    the rest alphabetically. One item per venue + native market + side."""
    rows = [r for r in rows if r.observed and r.quotes]
    ordered = sorted(rows, key=lambda r: (not r.has_position, _title_key(r)))
    out, seen = [], set()
    for r in ordered:
        side = "YES" if "YES" in r.quotes else next(iter(r.quotes))
        key = (r.venue, r.native_id, side)
        if key in seen:
            continue
        seen.add(key)
        out.append((r, r.quotes[side]))
        if len(out) >= limit:
            break
    return out


def market_title(row: MarketRow) -> str:
    """The market question, keeping the distinguishing threshold/outcome and date."""
    if row.title and row.outcome and row.outcome not in row.title:
        return f"{row.title} — {row.outcome}"
    return row.title or row.outcome or row.native_id


def short_label(row: MarketRow) -> str:
    """A compact tape label: the outcome when present (it carries the threshold)."""
    return row.outcome or row.native_id


def page_slice(items: list, page: int, size: int = PAGE_SIZE) -> tuple[list, int]:
    pages = max(1, -(-len(items) // size))
    page = min(max(1, page), pages)
    return items[(page - 1) * size: page * size], pages


# --------------------------------------------------------------------------- across venues (best_price, ADR 0027)

# The comparator's four claims, always shown separately and in this order; never merged into one
# "best" verdict. (label, what the figure is)
CLAIM_LABELS: dict[str, tuple[str, str]] = {
    "BEST_OBSERVED_QUOTE": (
        "Best observed quote",
        "Lowest top-of-book ask per contract from a fresh captured book. A quote, not a fill for the size."),
    "BEST_GROSS_COST_FOR_SIZE": (
        "Best gross cost for size",
        "Lowest cost of the whole evaluated size from a fresh captured ladder, before fees."),
    "BEST_VERIFIED_TOTAL_COST": (
        "Best verified total cost",
        "Lowest total with fees, only where the fee evidence supports a claim. Under a conservative bound the "
        "figure is an upper bound: the lowest bound, not a proven order."),
    "BEST_ACCOUNT_FEASIBLE_ROUTE": (
        "Best account-feasible route",
        "The verified total, only on a connected account with capital eligible under the starter rule. Execution "
        "is never authorized."),
}
CLAIM_ORDER = tuple(CLAIM_LABELS)
TOTAL_CLAIMS = ("BEST_VERIFIED_TOTAL_COST", "BEST_ACCOUNT_FEASIBLE_ROUTE")


def claim_value_text(claim: Any, route: Any) -> str | None:
    """The claim's own figure: a quote is cents per contract, the others dollars for the whole size.
    A total under a conservative fee bound reads "at most"; an exact total that carries the claim
    allowance says so (the exact debit is on the route row)."""
    if claim is None or not claim.supported or claim.value is None:
        return None
    if claim.kind == "BEST_OBSERVED_QUOTE":
        return cents(claim.value)
    text = money(claim.value)
    if claim.kind in TOTAL_CLAIMS and route is not None:
        if route.fee_status == "CONSERVATIVE_BOUND":
            return f"at most {text}"
        if route.total_cost != claim.value:  # an exact fee, but the claim figure carries the record's allowance
            return f"{text} incl. claim allowance"
    return text


FEE_STATUS_NOTES = {
    "VERIFIED": "Verified (exact)",
    "CONSERVATIVE_BOUND": "Partly verified · conservative bound",
    "UNVERIFIED": "Unverified estimate — not claim-grade",
    "UNSUPPORTED": "Unavailable: no fee model",
}
# The comparator judges a book's freshness at its own `as_of` (the recorded decision time), never
# now: the labels say so, and the page shows the book's age relative to now beside them.
ROUTE_FRESHNESS = {"fresh": ("FRESH", "Fresh at decision time"),
                   "stale": ("NOT_FRESH", "Stale at decision time — not ranked"),
                   "unknown": ("UNKNOWN", "Book age unknown — not ranked")}


def policy_label(row: Mapping[str, Any] | None) -> str:
    """"H · sizing-v2-candidate v1" from a panel's policy fields (letter optional)."""
    if not isinstance(row, Mapping):
        return "policy unknown"
    head = " · ".join(str(x) for x in (row.get("letter"), row.get("policy_id")) if x)
    return f"{head} v{row['policy_version']}" if row.get("policy_version") else (head or "policy unknown")


def route_freshness(value: Any) -> tuple[str, str]:
    """(state code, label) for a route's book freshness at the comparison's as-of time."""
    return ROUTE_FRESHNESS.get(str(value).lower(), ("UNKNOWN", "Book age unknown — not ranked"))


# --------------------------------------------------------------------------- notification origin (ADR 0020)

ORIGIN_ORDER = ("PRODUCTION", "TEST", "DEPLOYMENT_VERIFICATION", "MANUAL_DIAGNOSTIC", "REPLAY", "DEMO")


def origin_code(origin: Any) -> str:
    """The state-vocabulary code for a notification origin; an unrecognised value is ORIGIN_UNKNOWN."""
    return f"ORIGIN_{origin}" if origin in ORIGIN_ORDER else "ORIGIN_UNKNOWN"


def odds_state(status: Mapping[str, Any] | None) -> str:
    """The Odds API card state. ACTIVE is shown only with a verified live read; a status that
    claims ACTIVE without one is shown as UNVERIFIED, never as connected."""
    from ..odds_pilot import DASHBOARD_STATES

    state = str(_get(status, "state") or "UNKNOWN")
    if state not in DASHBOARD_STATES:
        return "UNKNOWN"  # never shown as reported: an unexpected word (e.g. "CONNECTED") is unknown
    if state == "ACTIVE" and _get(status, "live_read_verified") is not True:
        return "UNVERIFIED"
    return state


ODDS_MARKET_LABELS = {"h2h": "Moneyline", "spreads": "Spread", "totals": "Total"}


def odds_market_label(key: Any) -> str:
    """A provider market key in plain words, the key kept: "Moneyline (h2h)"; unknown keys raw."""
    word = ODDS_MARKET_LABELS.get(str(key))
    return f"{word} ({key})" if word else str(key)


def freshness_code(value: Any) -> str:
    """A `freshness.Freshness` (or its text) as the state-vocabulary code: FRESH / STALE / UNKNOWN."""
    text = getattr(value, "value", value)
    return str(text).upper() if text is not None else "UNKNOWN"


SPORT_LABELS = {"americanfootball_nfl": "NFL"}  # provider sport keys with a plain name; others stay raw


def sport_label(sport: Any) -> str:
    return SPORT_LABELS.get(str(sport), str(sport))


def odds_event_label(away: Any, home: Any, event_id: Any) -> str:
    """"Away @ Home" as the provider names the teams; the event id when either is missing."""
    if isinstance(away, str) and away and isinstance(home, str) and home:
        return f"{away} @ {home}"
    return f"Event {event_id}"


def _get(mapping: Any, key: str) -> Any:
    return mapping.get(key) if isinstance(mapping, Mapping) else None

