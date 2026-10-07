"""The isolated execution package stays isolated (ADR 0043).

- Nothing outside `edge_lab/execution/` imports it: research, the dashboard and the CLI cannot reach a
  signer, a transport or the execution journal.
- The package imports only the standard library, its own modules and an allowlist of canonical owners,
  and never a protected-label owner or the research store.
- `cryptography` is imported by `execution/signer.py` only.
- FIXTURE is the only authorized environment. DEMO and PRODUCTION egress need a reviewed change of
  `model.AUTHORIZED_ENVIRONMENTS` together with the owner's recorded approval phrase.

Each scan is mutation-checked: a probe line that breaks the rule is shown to be caught.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
ROOT = SRC.parent
PACKAGE = SRC / "edge_lab" / "execution"

# Canonical owners the package may import (`from .. import risk`, `from ..risk import ...`).
ALLOWED_OWNERS = frozenset({"execution_ticket", "risk", "fee_schedules", "opportunity", "freshness", "redaction",
                            "venues"})
# Never imported by the package, whatever the allowlist says: protected labels, research ledgers and the store.
PROTECTED = frozenset({"sports_evidence", "exp002_timing", "odds_schedule", "price_observations", "odds_consensus",
                       "experiments", "settlement", "forward", "shadow_ledger", "storage", "exp001_baseline",
                       "exp001_shadow", "exp001_stageb", "dataset_exp001", "describe_exp001"})
THIRD_PARTY = {"cryptography": frozenset({"edge_lab/execution/signer.py"})}

_DYNAMIC = re.compile(r"import_module\(|__import__\(|importlib\b")


def _rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


def _imports(text: str, rel: str) -> list[tuple[int, str]]:
    """(line, absolute dotted module) for every import in `text`, relative imports resolved for `rel`."""
    package_parts = rel.removesuffix(".py").split("/")[:-1]
    out = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - (node.level - 1)]
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            out.append((node.lineno, mod))
            out += [(node.lineno, f"{mod}.{a.name}") for a in node.names]  # `from . import execution`
    return out


def _outside_violations(rel: str, text: str) -> list[str]:
    hits = [f"{rel}:{n}: imports {m}" for n, m in _imports(text, rel)
            if m == "edge_lab.execution" or m.startswith("edge_lab.execution.")]
    hits += [f"{rel}:{n}: dynamic import names the execution package" for n, line in enumerate(text.splitlines(), 1)
             if _DYNAMIC.search(line) and "execution" in line and "execution_ticket" not in line]
    return hits


def _inside_violations(rel: str, text: str) -> list[str]:
    hits = []
    stdlib = sys.stdlib_module_names
    for n, mod in _imports(text, rel):
        top = mod.split(".")[0]
        if top == "edge_lab":
            parts = mod.split(".")
            if len(parts) == 1:
                continue  # `from .. import risk` also yields bare "edge_lab"; its "edge_lab.risk" entry is judged
            if parts[1] == "execution":
                continue  # its own modules
            if parts[1] in PROTECTED or parts[1] not in ALLOWED_OWNERS:
                hits.append(f"{rel}:{n}: imports edge_lab.{parts[1]}, not an allowed owner")
        elif top in THIRD_PARTY:
            if rel not in THIRD_PARTY[top]:
                hits.append(f"{rel}:{n}: imports {top} outside {sorted(THIRD_PARTY[top])}")
        elif top not in stdlib and top != "__future__":
            hits.append(f"{rel}:{n}: imports third-party {top}")
    hits += [f"{rel}:{n}: dynamic import" for n, line in enumerate(text.splitlines(), 1) if _DYNAMIC.search(line)]
    return hits


def _files():
    return sorted(SRC.rglob("*.py"))


def test_the_package_exists_and_the_scan_is_not_vacuous():
    assert (PACKAGE / "__init__.py").is_file() and (PACKAGE / "model.py").is_file()
    assert len([p for p in _files() if not _rel(p).startswith("edge_lab/execution/")]) > 50


def test_nothing_outside_the_package_imports_it():
    hits = [h for p in _files() if not _rel(p).startswith("edge_lab/execution/")
            for h in _outside_violations(_rel(p), p.read_text(encoding="utf-8"))]
    assert not hits, "\n".join(hits)


@pytest.mark.parametrize("rel,line", [
    ("edge_lab/cli.py", "from .execution import model"),
    ("edge_lab/cli.py", "from . import execution"),
    ("edge_lab/risk.py", "import edge_lab.execution.signer"),
    ("edge_lab/dashboard/app.py", "from ..execution.transport import send"),
    ("edge_lab/dashboard/views/research.py", "from ...execution import journal"),
    ("edge_lab/daily.py", "mod = importlib.import_module('edge_lab.execution.transport')"),
])
def test_an_outside_import_is_caught(rel, line):
    assert _outside_violations(rel, line + "\n"), line


def test_the_package_imports_only_stdlib_its_own_modules_and_allowed_owners():
    hits = [h for p in PACKAGE.rglob("*.py") for h in _inside_violations(_rel(p), p.read_text(encoding="utf-8"))]
    assert not hits, "\n".join(hits)


@pytest.mark.parametrize("rel,line", [
    ("edge_lab/execution/journal.py", "from .. import storage"),
    ("edge_lab/execution/journal.py", "from ..shadow_ledger import replay"),
    ("edge_lab/execution/lifecycle.py", "from ..sports_evidence import report"),
    ("edge_lab/execution/model.py", "from .. import cli"),
    ("edge_lab/execution/model.py", "import requests"),
    ("edge_lab/execution/transport.py", "from cryptography.hazmat.primitives import hashes"),
    ("edge_lab/execution/model.py", "x = __import__('edge_lab.storage')"),
])
def test_a_forbidden_package_import_is_caught(rel, line):
    assert _inside_violations(rel, line + "\n"), line


def test_allowed_owner_imports_pass():
    assert not _inside_violations("edge_lab/execution/risk_gate.py", "from .. import risk\nfrom ..risk import RiskPolicy\n"
                                  "from .model import OrderIntent\nfrom decimal import Decimal\n")
    assert not _inside_violations("edge_lab/execution/signer.py",
                                  "from cryptography.hazmat.primitives.asymmetric import ed25519\n")


def test_protected_owners_are_never_allowed():
    assert not ALLOWED_OWNERS & PROTECTED


# ---------------------------------------------------------------- environment authorization

AUTHORIZATION_PHRASES = {
    # environment -> the phrase that must appear verbatim (whitespace-normalized) in docs/EXECUTION_PLAN.md
    "FIXTURE": "the isolated execution package may run in the FIXTURE environment only",
}


def test_only_fixture_egress_is_authorized_and_each_authorization_is_recorded():
    from edge_lab.execution.model import AUTHORIZED_ENVIRONMENTS, Environment, environment_authorized

    assert {e.value for e in Environment} == {"FIXTURE", "DEMO", "PRODUCTION"}
    assert AUTHORIZED_ENVIRONMENTS == frozenset({Environment.FIXTURE})
    assert environment_authorized(Environment.FIXTURE)
    assert not environment_authorized(Environment.DEMO) and not environment_authorized(Environment.PRODUCTION)
    plan = " ".join((ROOT / "docs" / "EXECUTION_PLAN.md").read_text(encoding="utf-8").split())
    for env in AUTHORIZED_ENVIRONMENTS:
        assert AUTHORIZATION_PHRASES[env.value] in plan, env


def test_authorization_has_one_owner():
    """No other module keeps its own list of authorized environments."""
    hits = [f"{_rel(p)}:{n}" for p in PACKAGE.rglob("*.py") if p.name != "model.py"
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if re.search(r"AUTHORIZED_ENVIRONMENTS\s*(\|=|=|\+=)(?!=)", line)]
    assert not hits, hits
