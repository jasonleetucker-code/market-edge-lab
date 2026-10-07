"""The isolated Kalshi execution package (ADR 0043). Offline and hard-disabled.

This is the only place execution code may live. Research modules, the dashboard and the CLI never
import it (`tests/invariants/test_execution_boundary.py`). Only the FIXTURE environment (fake
transport, disposable store) is authorized. DEMO and PRODUCTION egress stay disabled by reviewed
constants, and no flag, credential or configuration can enable them.

Modules:
- `model`: exact typed values (environment, side, action, quantity, price, intent, approval) shared by
  every other module.

Later packages add a journal, reservations, the lifecycle, the wire format, a signer and a
transport, each under the boundary's file-exact rules.
"""
