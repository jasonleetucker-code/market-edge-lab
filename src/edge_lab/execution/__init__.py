"""The isolated Kalshi execution package (ADR 0043). Offline and hard-disabled.

This is the only place execution code may live. Research modules, the dashboard and the CLI never
import it (`tests/invariants/test_execution_boundary.py`). Only the FIXTURE environment (fake
transport, disposable store) is authorized. DEMO and PRODUCTION egress stay disabled by reviewed
constants, and no flag, credential or configuration can enable them.

Modules:
- `model`: exact typed values (environment, side, action, quantity, price, intent, approval) shared by
  every other module.
- `journal` (package D): the private, append-only execution journal. Intent, approval, reservation and a
  PENDING_EGRESS attempt are committed in one transaction before any network call. Receipts and events are
  hash-chained.
- `reservations` (package E): the transactional cash and inventory authority with fencing. It is built on
  `execution_ticket.reserve_simultaneous_obligations`. A terminal order stays BOUND until a later account
  snapshot confirms it, and contradictions quarantine with no new risk.

- `control` (packages L/N): operating modes DISARMED … BOUNDED_AUTO, kill latches, incidents with
  acknowledged rearm, and automated-policy grant objects. It is pure: the orchestrator persists its events.

Later packages add the lifecycle, the wire format, a signer and a transport, each under the boundary's
file-exact rules.
"""
