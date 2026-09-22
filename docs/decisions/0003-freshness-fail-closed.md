# 0003 — Freshness is explicit, worst-of, and fails closed

Status: Accepted (2026-09-22)

**Problem.** Brisket can show last-known-good data when a source fails. A trading system
that does the same could act on an order book or forecast that is hours old, without
anyone noticing.

**Alternatives.** (a) A boolean `is_stale`, defaulting to fresh. (b) Staleness warnings only.
(c) A three-state `FRESH/STALE/UNKNOWN` with a fail-closed guard.

**Decision.** (c). A missing, naive, unparseable or future timestamp is `UNKNOWN`. Combining
states is worst-of. `require_fresh` raises unless the state is `FRESH`, and all future
decision code must call it. Maximum ages live per payload kind in the source registry, and
a kind with none configured is `UNKNOWN`.

**Tradeoffs.** Some false stops, for example on clock skew beyond 5 minutes or a missing
publish time. We prefer a missed trade to a trade on stale data.

**Reconsider if** fail-closed stops happen often enough in shadow mode to hide real
opportunities. Fix the timestamps then. Do not loosen the rule.
