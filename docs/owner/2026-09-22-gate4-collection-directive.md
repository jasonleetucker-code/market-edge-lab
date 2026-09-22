# Owner directive: Gate 4 execution, PR #13, scheduled read-only collection (2026-09-22)

Source: the owner's written instructions to the working agent session on 2026-09-22,
evening ET. There were two messages:
- a standalone authorization for scheduled collection on the Chase Upside VPS
- a mission directive for three lanes

Both appear below. The standalone authorization is recorded in full. The mission
directive's governing sections are recorded **verbatim**. After them come the owner's
answers to the agent's clarifying questions in the same session.

## 1. Scheduled read-only collection authorization (verbatim, complete)

> I explicitly authorize Market Edge Lab to set up and run unattended/scheduled read-only data collection on my existing Chase Upside VPS.
> This authorization includes:
>
> * public, unauthenticated Kalshi market and order-book collection;
> * the NWS/weather data required by the active experiments;
> * scheduled collection at the EXP-001 decision window, including the required follow-up capture 10–15 minutes later;
> * storing the collected data in Market Edge Lab's own database/data directory;
> * systemd services/timers needed to run the collector;
> * logs, health monitoring, failure reporting, backups, bounded retries, and reasonable resource limits;
> * using the existing Chase Upside VPS so long as a resource/headroom review shows that doing so will not materially endanger the existing Chase Upside application.
>
> Market Edge Lab must remain a separate service/repository from Brisket.
> This authorization does not authorize:
>
> * placing trades or orders;
> * authenticated trading APIs;
> * brokerage/exchange trading credentials;
> * deposits or withdrawals;
> * funded accounts;
> * paid APIs, subscriptions, hosting, or other paid services;
> * automatic financial decisions or real-money risk.
>
> Before activation, verify CPU, RAM, disk, service contention, scheduling, backup/recovery, and isolation from the existing Chase Upside services.
> If completing the deployment requires an action that only I can perform—such as providing SSH credentials, changing DNS, approving authentication, or another external account action—prepare everything possible first and then tell me the exact manual step I need to perform.
> Record this authorization durably in the repository's execution/owner-decision documentation so future agents know scheduled read-only collection is approved.
> Proceed with the minimum reliable collector deployment needed to start accumulating irreplaceable forward Stage B evidence as soon as practical.

## 2. Mission directive: owner decisions (verbatim)

> **PR #13**
> You are explicitly authorized to reconcile, review, and merge PR #13 yourself if:
>
> * it is updated/reconciled against current `main`;
> * it does not overwrite or weaken Gate 3 / EXP-001 frozen artifacts;
> * an independent read-only review finds no unresolved correctness blocker;
> * full supported CI is green on the exact final head;
> * the PR is mergeable.
>
> Do not merge it based only on its old Gate-2-era CI.

> **Scheduled forward collection**
> The owner authorizes read-only unattended/scheduled collection for Market Edge Lab for the purpose of gathering irreplaceable forward research evidence.
> This authorization includes:
>
> * public/unauthenticated Kalshi market and order-book collection;
> * required public weather/NWS collection;
> * fixed-time scheduling;
> * collection on the existing Chase Upside VPS if the resource/security review says it is safe;
> * local Market Edge database/storage;
> * logs;
> * health monitoring;
> * backups;
> * bounded retries;
> * service/timer configuration;
> * alerts for failed/partial runs;
> * resource limits.
>
> This authorization does NOT include:
>
> * order placement;
> * trading credentials;
> * authenticated brokerage/trading APIs;
> * deposits;
> * withdrawals;
> * funded accounts;
> * paid APIs or subscriptions;
> * paid cloud infrastructure;
> * automatic financial decisions.
>
> If deployment to the existing VPS requires modifying production DNS, TLS, credentials, or other owner-only infrastructure that cannot safely be done from the repository alone, prepare everything necessary and stop at the exact manual action required.

## 3. Mission directive: lanes (verbatim excerpts)

> **LANE A — GATE 4: EXECUTE FROZEN EXP-001**
> EXP-001 is frozen.
> Do not alter its model specification after seeing validation or test results.
> [...]
> 1. Fit V1 and V2 on the TRAIN period.
> 2. Evaluate them on VALIDATION using the exact frozen selection rule.
> 3. Record which model wins according to that rule.
> 4. Refit the selected variant according to the preregistration.
> 5. Open the TEST period exactly once.
> 6. Calculate Stage A results.
> 7. Record PASS or FAIL exactly as observed.
>
> No extra: variants; tuning; windows; thresholds; smoothing changes; seasonal definitions; distributions; feature searches.
> Do not run exploratory test-period analysis.
> Use `edge_lab.stats` for every interval/bootstrap procedure specified by the frozen design.
> [...]
> If EXP-001 fails, conclude it honestly.
> Do NOT tune EXP-001.
> Any follow-up model becomes a separately preregistered EXP-002 or later experiment.

> **LANE C — FORWARD STAGE-B COLLECTOR**
> This lane is now P0 because missed data cannot be reconstructed.
> [...]
> Capture the complete KXHIGHNY event/order-book state during the preregistered decision window:
> approximately 17:55–18:00 America/New_York.
> [...]
> Capture every required open bracket again 10–15 minutes later.
> A Stage B day is VALID only if:
>
> * the correct event/date is identified;
> * every open bracket is present at the first capture;
> * every open bracket is present at the second capture;
> * timestamps satisfy the frozen windows;
> * required inputs are fresh;
> * the run is internally consistent.
>
> Any missing bracket or missing second capture means the entire day is invalid.
> Never construct a partial valid day.
> [...]
> No order endpoint.
> No authentication.
> No trading keys.
> [...]
> Deploy Market Edge as a separate service.
> Do not merge codebases.

> **FIX ISSUE #16**
> [...]
> Tests must prove a successful routine scheduled collection is not incorrectly marked unhealthy solely because a deliberately separate collector was not supposed to run.
> Do not make a genuinely stale required source look healthy.

> **GATE / SCOPE BOUNDARIES**
> Do not begin: live trading; authenticated order execution; real-money testing; paid data; sports implementation; sportsbook collection; full dashboard build; adaptive bankroll/withdrawal automation.

## 4. Owner answers in the same session (recorded by the agent)

1. **The VPS.** The Chase Upside VPS is `chaseupside.com`, user `dynasty` (hostname
   `vmi3454985`, local SSH alias `chaseupside`, using an already-authorized key). The owner
   said: "Do not add, replace, or rotate SSH keys." They also said: "Proceed with the
   read-only VPS preflight first [...] Do not modify production until the preflight is
   complete and the planned Market Edge changes are reviewed against the authorization
   already given."
2. **Merge authority is extended.** The agent may squash-merge the docs PR, the
   forward-collector PR and the Gate 4 PR under the same conditions as PR #13:
   - independent review with no unresolved correctness blocker;
   - CI green on the exact final head;
   - the PR is mergeable.
3. **Attended laptop bridge approved.** If the VPS collector is not live by the
   2026-09-23 17:55 ET window, the agent may run that capture attended, from the owner's
   laptop session. No laptop scheduler may be left behind.
4. **Plan review.** The owner approved the plan in principle, with these required
   corrections:
   - **Env file:** readable only by root and the service account (e.g. `root:edgelab 0640`),
     tested during install.
   - **Status file:** in a separately readable directory. The private DB and backups must
     not become readable to anyone else.
   - **Fail closed on timing:** an out-of-window decision capture must be rejected by the
     timing gate *before* any order-book work, not captured and then labelled invalid.
