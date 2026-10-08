# Work Claims

One line per piece of work in flight. Rules: `docs/AGENT_OPERATING_SYSTEM.md` §5.
Add your row in your first commit and **delete it in your last**. Git history is the log.
The expiry is a UTC date no more than 7 days out. An expired row is not a live claim.

| Claim | Agent | Branch | Paths | Expires |
|---|---|---|---|---|
| #160 A/C: execution foundation, scope, boundary, ledger | Claude coordinator (laptop) | exec/a-c-foundation-r2 | src/edge_lab/execution/__init__.py, src/edge_lab/execution/model.py, tests/execution/test_model.py, tests/invariants/test_execution_boundary.py, tests/invariants/test_no_execution_paths.py, docs/decisions/0043-*, docs/strategy/KALSHI_EXECUTION_LEDGER.md, docs/EXECUTION_PLAN.md, docs/SECURITY.md, docs/owner/2026-10-07-*, pyproject.toml, .github/workflows/test.yml | 2026-10-14 |
| #160 D/E: journal, reservations, fencing | Claude journal lane | exec/d-e-journal | src/edge_lab/execution/journal.py, src/edge_lab/execution/reservations.py, tests/execution/test_journal*.py, tests/execution/test_reservations*.py | 2026-10-14 |
| #160 H: order lifecycle, fake venue | Claude lifecycle lane | exec/h-lifecycle | src/edge_lab/execution/lifecycle.py, src/edge_lab/execution/fake_venue.py, tests/execution/test_lifecycle*.py, tests/execution/test_fake_venue*.py | 2026-10-14 |
| #160 B/F: conformance, wire, signer, transport | Claude wire lane | exec/b-f-wire | docs/execution/**, src/edge_lab/execution/conformance.py, src/edge_lab/execution/kalshi_wire.py, src/edge_lab/execution/signer.py, src/edge_lab/execution/transport.py, tests/execution/test_conformance*.py, tests/execution/test_wire*.py, tests/execution/test_signer*.py, tests/execution/test_transport*.py, tests/fixtures/kalshi_exec/** | 2026-10-14 |
| #160 BF2: exact-type WireRequest; transport/signer decide from the endpoint spec | Claude BF2 writer | exec/bf2-exact-request | src/edge_lab/execution/kalshi_wire.py, src/edge_lab/execution/transport.py, src/edge_lab/execution/signer.py, src/edge_lab/execution/account.py, tests/execution/test_wire_exact_request.py, docs/decisions/0043-isolated-execution-boundary.md | 2026-10-15 |
