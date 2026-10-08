"""The setup and readiness manifest (Market v1 journey J1): what is missing, and the safe next step for each.

Static facts, transcribed from the canonical documents, never parsed from them at request time (the dashboard runs
from an installed wheel without the docs). Every item carries its source and a short verbatim `quote` from it, and
`tests/test_dashboard_journeys.py` checks each quote is still in that document, so an edited document breaks the
test instead of leaving a stale manifest. The code-level environment list is not here: it is read from the execution
status export (`environments`), because the dashboard never imports the execution package (ADR 0043).

Nothing here authorizes anything. A safe next step names who acts and where; none is an action this Terminal can
take (it has no command surface).
"""

from __future__ import annotations

from dataclasses import dataclass

PLAN = "docs/EXECUTION_PLAN.md"
LEDGER = "docs/strategy/KALSHI_EXECUTION_LEDGER.md"
PACKET = "docs/strategy/KALSHI_OWNER_ACTIVATION_PACKET.md"
ACCEPTANCE = "docs/strategy/MARKET_V1_ACCEPTANCE.md"
MANIFEST_VERSION = "ops-readiness-manifest/1 (2026-10-07 evening)"

KINDS = (("ENVIRONMENT", "Environments"), ("APPROVAL", "Owner approvals"),
         ("PERMISSION", "Permissions and credentials"), ("PROVIDER_FACT", "Provider facts to confirm"))
# state -> (label, kind). Nothing is green: an item here is missing by definition.
STATE_WORDS = {
    "NOT_AUTHORIZED": ("Not authorized", "warn"),
    "BLOCKED_EXTERNAL": ("Needs an owner or provider step", "warn"),
    "NEEDS_PREREQUISITE": ("Waits on an earlier step", "nd"),
    "UNCONFIRMED": ("Unconfirmed · conservative default in code", "warn"),
    "NEVER_REQUESTED": ("Never requested", "nd"),
}


@dataclass(frozen=True)
class Item:
    item_id: str
    kind: str
    title: str
    state: str
    detail: str
    next_step: str
    who: str
    source: str
    quote: str  # verbatim (whitespace-normalized) in `source`


_CONFIRM = ("Confirm against the venue (DEMO_OBSERVED or PRODUCTION_READ_VERIFIED), which needs Decision 1 or 2 "
            "first. Until then the offline code keeps its conservative treatment.")

ITEMS = (
    # ---- environments (the code's current value comes from the export; this is the documented authority)
    Item("env-demo", "ENVIRONMENT", "DEMO egress (mock funds)", "NOT_AUTHORIZED",
         "The execution package may not reach the venue's demo environment.",
         "Owner: Decision 1 of the activation packet (demo rehearsal). You create the demo account and key yourself, "
         "on the executor host; then the approval phrase is recorded in EXECUTION_PLAN and one reviewed PR adds DEMO.",
         "Owner", PLAN, "DEMO or PRODUCTION egress, including any change to"),
    Item("env-production", "ENVIRONMENT", "PRODUCTION reads and orders (real money)", "NOT_AUTHORIZED",
         "No production account is read and no order can be sent.",
         "Owner: Decision 2 (production account reads, no order) first; real orders only after Decision 3.",
         "Owner", PLAN, "demo mock orders and production account reads"),
    # ---- owner approvals
    Item("decision-1", "APPROVAL", "Decision 1 · demo rehearsal (packages K and R)", "BLOCKED_EXTERNAL",
         "Unlocks DEMO_LIFECYCLE_VERIFIED with mock funds only.",
         "Owner: read Decision 1 in the activation packet; choose the bounds (orders, quantity, market list).",
         "Owner", PACKET, "Decision 1 — demo rehearsal (packages K and R)"),
    Item("decision-2", "APPROVAL", "Decision 2 · production account reads (packages M and S)", "BLOCKED_EXTERNAL",
         "Unlocks PRODUCTION_ACCOUNT_SHADOW_VERIFIED. No order is ever sent.",
         "Owner: a risk decision, because Kalshi documents no read-only key scope: decline, accept a full-access key "
         "held only by the read-only process, or wait for a scoped key.",
         "Owner", PACKET, "Decision 2 — production account reads (packages M and S)"),
    Item("decision-3", "APPROVAL", "Decision 3 · tiny live pilot", "NEEDS_PREREQUISITE",
         "Needs a strategy that qualified on its own evidence; none has.",
         "None now. It is presented only after AUTOMATION_READY_FOR_DECLARED_PROFILE and a STRATEGY_QUALIFIED "
         "strategy.", "Owner, later", PACKET, "This needs a strategy that has separately qualified on its own evidence"),
    Item("decision-4", "APPROVAL", "Decision 4 · unattended automation", "NEEDS_PREREQUISITE",
         "UNATTENDED_LIVE_AUTHORIZED stays false.",
         "None now. Needs live and shadow reconciliation history and tested incident delivery first.",
         "Owner, later", PACKET, "UNATTENDED_LIVE_AUTHORIZED stays false"),
    Item("decision-6", "APPROVAL", "Decision 6 · automation grant (BOUNDED_AUTO)", "NOT_AUTHORIZED",
         "No grant is issued. Any grant shown elsewhere in this Terminal is a TEST fixture grant.",
         "None now. A grant needs a qualified strategy, Decisions 1 to 4 and owner-set risk limits, then its own "
         "owner decision recorded in EXECUTION_PLAN.", "Owner, later", PLAN,
         "issuing any BOUNDED_AUTO or other automated grant"),
    Item("risk-limits", "APPROVAL", "Risk-limit values", "BLOCKED_EXTERNAL",
         "The code ships placeholder limits that refuse every order until replaced.",
         "Owner: choose reserve floor, position, event, cluster and portfolio caps, loss limits, drawdown, orders "
         "per window and cooldown (activation packet, \"Risk-limit values you will eventually choose\").",
         "Owner", PLAN, "setting or changing live risk-limit values"),
    Item("service", "APPROVAL", "Executor service activation and its deploy", "NOT_AUTHORIZED",
         "No executor runs on the VPS; no unit, timer or schedule exists for it.",
         "Owner: a separate approval after package O ships its units disabled.", "Owner", PLAN,
         "Any later deploy, and any service activation, needs its own owner approval."),
    Item("decision-5", "APPROVAL", "Decision 5 · wallet intelligence sources (issue 168)", "NOT_AUTHORIZED",
         "The wallet lane runs on synthetic fixtures and documentation examples only.",
         "Owner: approve one bounded, one-off public read with a request budget and a terms check, if you want real "
         "data; each source is its own approval.", "Owner", PLAN,
         "any network read of Polymarket, chain, Hyperliquid or other wallet sources"),
    Item("wallet-slot", "APPROVAL", "A research slot for an empirical wallet evaluation", "BLOCKED_EXTERNAL",
         "Both #96 family slots are taken (EXP-002 and paused EXP-003).",
         "Owner: end or replace a family, or grant an owner exception.", "Owner", PLAN,
         "an empirical wallet-research evaluation, which needs its own family slot and budget (#96 limit)"),
    # ---- permissions and credentials
    Item("credentials", "PERMISSION", "Venue account, API key and private key", "NOT_AUTHORIZED",
         "No credential exists anywhere in this system, and none may be requested.",
         "Owner, on the executor host only, after the matching decision. Never paste a key into a chat, issue or "
         "commit.", "Owner", PLAN, "creating, installing, reading or requesting any credential, key or account"),
    Item("key-scope", "PERMISSION", "API-key scope (read-only keys)", "BLOCKED_EXTERNAL",
         "Kalshi documents no permission scopes, read-only keys or IP allowlist: a key that can read can trade.",
         "Owner: the Decision 2 risk choice. Agents re-check the documentation before asking.", "Owner, provider",
         LEDGER, "Kalshi's api_keys page documents no permission scopes"),
    Item("withdrawal", "PERMISSION", "Withdrawal or transfer permission", "NEVER_REQUESTED",
         "Never part of any decision.", "None. It is never requested.", "Nobody", PACKET,
         "withdrawal or transfer permission on any key"),
    # ---- provider facts the offline code depends on (ledger: "Facts that must be confirmed")
    Item("fact-skew", "PROVIDER_FACT", "Timestamp skew between fills and snapshots (provisionally 2 s)",
         "UNCONFIRMED", "Larger drift would quarantine normal flows falsely.", _CONFIRM, "Agent, after a decision",
         LEDGER, "`lifecycle.TIMESTAMP_SKEW` (provisionally 2 s)"),
    Item("fact-not-found", "PROVIDER_FACT", "Not-found delay (provisionally 30 s)", "UNCONFIRMED",
         "It compares our clock with the venue's.", _CONFIRM, "Agent, after a decision", LEDGER,
         "`lifecycle.NOT_FOUND_MIN_DELAY` (provisionally 30 s)"),
    Item("fact-balance", "PROVIDER_FACT", "Whether the available balance excludes resting-order holds", "UNCONFIRMED",
         "It drives the venue-held credit; the cash basis stays UNKNOWN until settled (ACC-02).", _CONFIRM,
         "Agent, after a decision", LEDGER, "Whether the available balance already excludes cash held by resting "
                                            "orders"),
    Item("fact-409", "PROVIDER_FACT", "What a 409 on a repeated client order id means", "UNCONFIRMED",
         "Treated as ambiguous: the attempt stays unknown and is reconciled, never re-sent.", _CONFIRM,
         "Agent, after a decision", LEDGER, "What a 409 on a repeated `client_order_id` means"),
    Item("fact-reduce-to", "PROVIDER_FACT", "The meaning of reduce_to", "UNCONFIRMED", "It is refused.", _CONFIRM,
         "Agent, after a decision", LEDGER, "The meaning of `reduce_to`"),
    Item("fact-post-only", "PROVIDER_FACT", "Post-only crossing and amend time priority", "UNCONFIRMED",
         "Whether post_only crosses or rejects, and whether an amend keeps priority.", _CONFIRM,
         "Agent, after a decision", LEDGER, "Whether `post_only` crosses or rejects"),
    Item("fact-sale-fees", "PROVIDER_FACT", "How sales are charged fees", "UNCONFIRMED",
         "The risk gate bounds a sale's fee with the buy formula at the worst price.", _CONFIRM,
         "Agent, after a decision", LEDGER, "How sales are charged fees."),
)

# Market v1 readiness tracks (acceptance manifest §1), as recorded. A track's state changes only there.
TRACKS = (
    ("SOFTWARE_V1_COMPLETE", "NOT MET", "| SOFTWARE_V1_COMPLETE | NOT MET |"),
    ("OFFLINE_AUTONOMOUS_LOOP_VERIFIED", "NOT MET", "| OFFLINE_AUTONOMOUS_LOOP_VERIFIED | NOT MET |"),
    ("DEMO_LIFECYCLE_VERIFIED", "NOT MET; BLOCKED_EXTERNAL", "| DEMO_LIFECYCLE_VERIFIED | NOT MET; BLOCKED_EXTERNAL |"),
    ("PRODUCTION_ACCOUNT_SHADOW_VERIFIED", "NOT MET; BLOCKED_EXTERNAL",
     "| PRODUCTION_ACCOUNT_SHADOW_VERIFIED | NOT MET; BLOCKED_EXTERNAL |"),
    ("AUTOMATION_READY_FOR_DECLARED_PROFILE", "NOT MET", "| AUTOMATION_READY_FOR_DECLARED_PROFILE | NOT MET |"),
    ("STRATEGY_QUALIFIED", "NONE", "| STRATEGY_QUALIFIED | NONE |"),
    ("LIVE_AUTHORIZED", "FALSE", "| LIVE_AUTHORIZED | FALSE |"),
    ("UNATTENDED_LIVE_AUTHORIZED", "FALSE", "| UNATTENDED_LIVE_AUTHORIZED | FALSE |"),
)
# The documented authority for environments, shown when the export cannot be read (never as the code's value).
DOCUMENTED_AUTHORIZED = ("FIXTURE",)
DOCUMENTED_AUTHORIZED_QUOTE = "the isolated execution package may run in the FIXTURE environment only"
