# Kalshi execution — owner setup and approval packet (#160)

**Status: DRAFT, prepared early, as the directive asks.** Nothing here is approved. Each section is a separate
decision, recorded in `docs/EXECUTION_PLAN.md` when you make it. Some facts are marked *pending conformance*: they
wait on the conformance pack (`docs/execution/KALSHI_CONFORMANCE.md`, package B), and this packet will be updated
from it before you are asked.

Never paste a password, API key, private key or MFA code into a chat, an issue or a commit. Every step below that
touches a credential is done by you, on the machine that will hold it.

## Decision 1 — demo rehearsal (packages K and R)

Unlocks `DEMO_LIFECYCLE_VERIFIED`. Mock funds only.

**What you would do:**
1. Create a Kalshi **demo** account. The demo is separate from production, with its own login and its own keys
   (help.kalshi.com, "Creating and using a demo account"). It needs a different password from production.
2. In the demo web app, create an API key. You download its private key file once. *Pending conformance:* whether
   demo keys can be Ed25519, which is the recommended type, and whether any scope or permission setting exists.
3. Put the private key file on the executor host only:
   - in a path outside the repository, owned by the executor's own service user, with mode 0600;
   - never in git, `.env`, a chat or a backup bundle meant for research data.

   Package O defines the exact path and user. Until then the key is not installed anywhere.
4. Tell the session, in words, that the demo key is installed. Do not paste its contents.

**What you would approve (proposed wording):**
- "the isolated execution package may run in the DEMO environment", for the bounded rehearsal below.
- **Bounds (proposed; you choose the values):**
  - one demo account and its primary subaccount;
  - at most N mock orders in total, e.g. 20;
  - quantity at most Q contracts per order, e.g. 5;
  - only markets on a named demo list;
  - only these operations: create, cancel, amend (if supported) and account reads;
  - a synthetic signal clearly labelled demo;
  - no self-trading or wash orders to force fills.
- What the agent then does:
  - adds `Environment.DEMO` to `execution.model.AUTHORIZED_ENVIRONMENTS` and a key loader, in one reviewed PR that
    quotes the approval phrase;
  - runs the rehearsal (package R);
  - records every receipt.

**What it does not authorize:** production, real money, unattended operation, and use of the demo key for anything
but the rehearsal.

## Decision 2 — production account reads (packages M and S)

Unlocks `PRODUCTION_ACCOUNT_SHADOW_VERIFIED`. No order is ever sent.

**Open fact that decides this packet** (*pending conformance*): can a Kalshi production API key be limited to
reads? The campaign rule is "no provider default-full-access key accepted without scope evidence".

- If read-only scope exists: create a read-only production key and install it as in Decision 1, on the executor
  host only.
- If it does not exist: a full-access key used by a read-only process is a real risk decision, because the key
  itself could trade if stolen. Your options are then:
  - (a) decline for now;
  - (b) accept a full-access key held only by the read-only shadow process, with rotation and an IP allowlist if
    Kalshi offers one;
  - (c) wait for a scoped key.

**What you would approve (proposed):**
- "the isolated execution package may read the PRODUCTION account (no financial writes)";
- the exact subaccount;
- the read endpoints and a read budget per hour;
- which local projections may be shown on the private Terminal.

**Never included:** withdrawal or transfer permission on any key.

## Decision 3 — tiny live pilot (after T; not part of this campaign's finish line)

This needs a strategy that has separately qualified on its own evidence; no strategy has yet. It also needs an exact
capital amount, risk limits, a stop policy and an operator schedule. It is presented only after
`KALSHI_AUTOMATION_READY_FOR_DECLARED_PROFILE`. LIVE_AUTHORIZED stays false until you decide it.

## Decision 4 — unattended automation (later)

This needs live and shadow reconciliation history, tested incident delivery and an automated-approval policy:
universe, turnover, loss, concentration and per-event limits. UNATTENDED_LIVE_AUTHORIZED stays false.

## Risk-limit values you will eventually choose

Packages I and N need numbers only you can set. The engineering ships with conservative placeholders that block new
risk until they are replaced. The list mirrors `risk.RiskPolicy`:
- reserve floor;
- per-position, per-event, per-cluster and portfolio caps;
- daily and weekly loss limits;
- maximum drawdown;
- orders per window;
- per-market cooldown.
