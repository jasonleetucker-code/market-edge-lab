# 0008 — No scheduled (cron) collector yet

Status: Accepted (2026-09-22)

**Problem.** Building history needs regular collection. The NWS API keeps only the last few
days of CLI products, and live order books are only observable at the time.

**Alternatives.**
(a) An hourly GitHub Actions cron that writes SQLite to workflow artifacts.
(b) An Actions cron that commits data to the repository.
(c) Defer until there is a proper durable store, and backfill gaps from archives.

**Decision.** (c) for now.
- Artifacts expire and are awkward to chain into one growing database, so (a) produces a
  misleading "pipeline" of disconnected fragments.
- (b) bloats git history with binary data and mixes code review with data.
- Gate 2 did not need scheduling: CLI history is recoverable from the IEM archive, and
  settled markets from Kalshi's historical API.
- For reference, an hourly job of about 1 minute would be roughly 720 job runs and 720+
  billable minutes a month (each job rounds up to a whole minute) against the private
  repo's Actions allowance. Actually committing to that needs owner approval under the cost
  policy in `docs/EXECUTION_PLAN.md`.

**Tradeoffs.** Point-in-time order books and forecast issuances are collected only when
someone runs `edge-lab collect`. Gate 3 must document this gap. It cannot be backfilled for
order books.

**Reconsider when** gate 3 needs forward-collected order books or forecasts at fixed
decision times. At that point, propose a design with a durable store (e.g. a small
low-cost VM or object storage), a runtime and minute estimate, concurrency protection, a
kill switch and an owner decision.
