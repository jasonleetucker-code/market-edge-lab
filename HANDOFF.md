# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-22, by the Gate 4 / collection-authorization docs PR. This is an
interim state for the three-lane mission in
`docs/owner/2026-09-22-gate4-collection-directive.md`. It is rewritten when the mission ends._

```
STATUS: PARTIAL: Gate 4 is active. Three lanes are in flight: the Gate 4 EXP-001
  execution, the PR #13 reconciliation, and the forward Stage-B collector with #16 and the
  VPS deployment. Owner decisions for all three are recorded.
ACCEPTANCE: the owner's 2026-09-22 Gate 4 / collection directive (verbatim in
  docs/owner/2026-09-22-gate4-collection-directive.md)
EVIDENCE:
  - Gate 3 merged in PR #14 (2f5d640). The Windows portability fixes merged in PR #15
    (7c93f78).
  - Owner laptop (Windows, Python 3.12) at the PR #15 head: 231 tests passed.
    `edge-lab collect --source all` succeeded with no anomalies (reported in issue #16).
  - Scheduled read-only collection on the Chase Upside VPS is authorized. ADR 0012
    supersedes ADR 0008.
  - A read-only VPS headroom review passed: docs/deploy/VPS_REVIEW_2026-09-22.md (4 vCPU,
    7.9 GB RAM with at least 3.9 GB available over 7 days, 65 GB disk free, Brisket capped
    at 3G + 2G). sudo needs the owner's password, so install is an owner step.
  - EXP-001 is PREREGISTERED and frozen (frozen_fields SHA-256 258baaf6…). Dataset
    EXP-001-pit-v2 SHA-256 1794b23c…
UNRESOLVED:
  - Gate 4 Stage A has not been run yet.
  - PR #13 is being reconciled against current main. Its old Gate-2-era CI is not accepted.
  - The forward collector is not built or deployed yet, so no Stage B days have been
    captured. Every missed 17:55 ET window is lost for good.
  - Issue #16 (routine collect vs default health) is open.
  - Fee coefficient 0.07: re-verify against Kalshi's fee schedule before any Stage B result.
  - PFMOKX issuance thinned from mid-2025. This is disclosed, and it may hurt Stage A
    calibration.
  - Test-period protection is procedural (dataset.csv contains test rows).
  - Carried from Gate 2: TWC cannot be checked directly; the NHIGH delayed-determination
    rule rests on one observation.
BLOCKERS: NONE for Gate 4. The VPS install and timer activation need two owner sudo
  commands. They will be handed over as exact command lines once the collector PR merges.
NEXT ACTION: Build and merge the forward collector with the #16 fix, then hand the owner
  the install command before the first capture of the next window. The PFM capture runs at
  17:45 ET and the decision window is 17:55–18:00 ET on 2026-09-23 (D = 09-24). If it is
  not live by then, use the attended laptop bridge.
```

## 30-day directive status (issue #11, target 2026-10-22)

- **Remaining calendar days:** 30.
- **Critical path:** forward collector live (P0, next window 2026-09-23 17:55 ET for
  D = 09-24) → Gate 4 Stage A result → market-vs-model engine → shadow ledger → risk
  foundation → dashboard → deployment.
- **Blockers:** only the owner's sudo steps on the VPS. The scheduled-collection decision
  that previously blocked Stage B was made on 2026-09-22.
- **Scope changes:** none. The #10 hosting idea is authorized only for the headless
  collector. Dashboard, DNS, TLS and auth remain unauthorized.

## Open questions for the owner

1. **Standing merge rule.** It is answered for this mission only: agents may merge PR #13
   and the docs, collector and Gate 4 PRs under the recorded conditions. There is still no
   general rule for docs- or test-only PRs.
2. **Alert channel.** Should failed or partial collection runs push somewhere? A private
   ntfy topic URL in `/etc/market-edge-lab/env` would work. Without one, alerts go to
   journald and the status file only.
