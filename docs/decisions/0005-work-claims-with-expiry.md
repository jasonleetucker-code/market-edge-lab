# 0005 — Work claims are short-lived single lines

Status: Accepted (2026-09-22)

**Problem.** Parallel agents duplicate or clobber each other's work. Brisket's claims table
did prevent collisions, but it grew to 312 KB of narrative rows with no expiry, and its stale
rows caused false blocks.

**Decision.** `docs/WORK_CLAIMS.md` has one line per claim: `Claim | Agent | Branch | Paths |
Expires`. Expiry is at most 7 days out (a convention; CI cannot know when the row was written). The row is deleted in the claimant's last commit, and
an expired row is void. A test checks the row format and ISO expiry date.

**Tradeoffs.** Claims stay advisory. Open PRs and branches remain the primary evidence of
work in flight.

**Reconsider if** agents regularly collide despite claims. At that point, a lock
enforced by a script becomes worth its cost.
