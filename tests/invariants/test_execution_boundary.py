"""The isolated execution package stays isolated (ADR 0043).

Outside the package (`src/`, `scripts/` and `deploy/`):
- no import of it, in any AST form;
- no attribute access through `edge_lab`;
- no string naming it;
- no string expression that builds an `edge_lab.` / `edge_lab/` path.

Inside the package:
- **Standard library, restricted per file.**
  - Network modules: `transport.py` only.
  - `sqlite3`: the journal and reservation files only.
  - Process, dynamic-import and environment access: nowhere.
- **Own modules, plus an allowlist of canonical owners.** Never a protected-label owner or the research
  store. The allowed owners' own transitive imports are checked too; the one documented exception is
  pinned below.
- **`cryptography`:** `execution/signer.py` only.

FIXTURE is the only authorized environment. DEMO and PRODUCTION egress need a reviewed change of
`model.AUTHORIZED_ENVIRONMENTS` together with the owner's recorded approval phrase.

Static scans catch ordinary and careless paths, not determined obfuscation (for example a name
assembled from character codes). The hard control is the separate executor process and service
user (package O) plus review. Each rule here is mutation-checked: a probe that breaks it is caught.
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
OUTSIDE_DIRS = (SRC, ROOT / "scripts", ROOT / "deploy")

# Canonical owners the package may import (`from .. import risk`, `from ..risk import ...`).
ALLOWED_OWNERS = frozenset({"execution_ticket", "risk", "fee_schedules", "opportunity", "freshness", "redaction",
                            "venues"})
# Never reachable from the package, directly or through an allowed owner: protected labels,
# research ledgers and the research store.
PROTECTED = frozenset({"sports_evidence", "exp002_timing", "odds_schedule", "price_observations", "odds_consensus",
                       "experiments", "settlement", "forward", "shadow_ledger", "storage", "exp001_baseline",
                       "exp001_shadow", "exp001_stageb", "dataset_exp001", "describe_exp001"})
# The single pinned exception, with its reason: `risk` imports `shadow_ledger` for the `AccountState` type of the
# legacy shadow `assess()`. Package I gives risk rules a versioned account projection and removes this edge.
TRANSITIVE_EXEMPT = {("risk", "shadow_ledger"): "AccountState type for legacy shadow assess(); package I removes it"}

THIRD_PARTY = {"cryptography": frozenset({"edge_lab/execution/signer.py"})}
NETWORK_MODULES = frozenset({"socket", "ssl", "http", "urllib", "ftplib", "smtplib", "poplib", "imaplib", "telnetlib",
                             "xmlrpc", "asyncio", "selectors", "socketserver", "webbrowser", "email"})
NETWORK_FILES = frozenset({"edge_lab/execution/transport.py"})
SQLITE_FILES = frozenset({"edge_lab/execution/journal.py", "edge_lab/execution/reservations.py"})
# Harmless helpers inside network packages, allowed anywhere in the package (they open nothing).
NETWORK_HELPERS = frozenset({"http", "http.HTTPStatus", "urllib", "urllib.parse"})
BANNED_IN_PACKAGE = frozenset({"subprocess", "multiprocessing", "concurrent", "ctypes", "pty", "importlib", "runpy",
                               "pkgutil", "zipimport", "code", "codeop", "pickle", "shelve", "marshal"})
# Names that may not be imported from `os` (`from os import system`), nor used as `os.<name>`.
_OS_BANNED = r"system|popen|exec\w*|spawn\w*|posix_spawn\w*|fork\w*|environ\w*|getenv\w*|putenv|unsetenv"
_OS_BANNED_NAME = re.compile(rf"(?:{_OS_BANNED})")
_BANNED_CALLS = re.compile(rf"\bos\.(?:{_OS_BANNED})\b|__import__\s*\(|\bgetenv\s*\(|\beval\s*\(|\bexec\s*\(")
_NAMES_PACKAGE = re.compile(r"edge_lab\s*[./\\]\s*execution(?![a-z0-9_])")
_BUILDS_PATH = re.compile(r"(^|[^a-z0-9_])edge_lab\s*[./\\]\s*($|%|\{)")
_EXECUTION_PIECE = re.compile(r"^\.?execution([./][a-z_].*)?$")
# Calls that turn strings into module paths: a piece naming the package must not reach them.
_IMPORTISH_CALLS = frozenset({"import_module", "__import__", "resolve_name", "run_module", "run_path", "find_spec",
                              "join", "format"})


def _rel(path: Path) -> str:
    try:
        return path.relative_to(SRC).as_posix()
    except ValueError:
        return path.relative_to(ROOT).as_posix()


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


def _names_package(text: str) -> bool:
    return bool(_NAMES_PACKAGE.search(text))


def _outside_violations(rel: str, text: str) -> list[str]:
    hits = [f"{rel}:{n}: imports {m}" for n, m in _imports(text, rel)
            if m == "edge_lab.execution" or m.startswith("edge_lab.execution.")]
    tree = ast.parse(text)
    docstrings = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Call):
            func = node.func
            fname = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
            if fname in _IMPORTISH_CALLS:
                pieces = [c.value for arg in [*node.args, *(k.value for k in node.keywords)] for c in ast.walk(arg)
                          if isinstance(c, ast.Constant) and isinstance(c.value, str)]
                if isinstance(func, ast.Attribute):  # "edge_lab.{}".format(...), ".".join([...])
                    pieces += [c.value for c in ast.walk(func.value) if isinstance(c, ast.Constant)
                               and isinstance(c.value, str)]
                receiver = [c.value for c in ast.walk(func.value) if isinstance(c, ast.Constant)
                            and isinstance(c.value, str)] if isinstance(func, ast.Attribute) else []
                if fname == "format" and any(_BUILDS_PATH.search(p) for p in receiver):
                    hits.append(f"{rel}:{line}: formats an edge_lab module path")
                if fname == "join" and "edge_lab" in pieces and any(r in (".", "/") for r in receiver):
                    hits.append(f"{rel}:{line}: joins an edge_lab module path")
                if any(_EXECUTION_PIECE.match(p) for p in pieces) or (
                        fname not in ("join", "format") and any(p in ("edge_lab", "edge_lab.") for p in pieces)
                        and any(_EXECUTION_PIECE.match(p.lstrip(".")) for p in pieces)):
                    hits.append(f"{rel}:{line}: an import-style call is given a piece naming the package")
        if isinstance(node, ast.Attribute) and node.attr == "execution":
            base = node.value
            if (isinstance(base, ast.Name) and base.id == "edge_lab") or (
                    isinstance(base, ast.Attribute) and base.attr == "edge_lab"):
                hits.append(f"{rel}:{line}: reaches edge_lab.execution by attribute")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings \
                and _names_package(node.value):
            hits.append(f"{rel}:{line}: a string names the execution package")
        elif isinstance(node, (ast.BinOp, ast.JoinedStr)):
            parts = [c.value for c in ast.walk(node) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
            if any(_BUILDS_PATH.search(p) for p in parts) or (
                    "edge_lab" in parts and any(_EXECUTION_PIECE.match(p.lstrip(".")) for p in parts)):
                hits.append(f"{rel}:{line}: builds an edge_lab module path from pieces")
    return hits


def _owner_deps(owner: str) -> set[str]:
    path = SRC / "edge_lab" / f"{owner}.py"
    if not path.is_file():
        return set()
    out = set()
    for _, mod in _imports(path.read_text(encoding="utf-8"), f"edge_lab/{owner}.py"):
        parts = mod.split(".")
        if parts[0] == "edge_lab" and len(parts) >= 2:
            out.add(parts[1])
    return out


def _inside_violations(rel: str, text: str) -> list[str]:
    hits = []
    stdlib = sys.stdlib_module_names
    for n, mod in _imports(text, rel):
        top = mod.split(".")[0]
        if mod.startswith("os.") and _OS_BANNED_NAME.fullmatch(mod[3:]):
            hits.append(f"{rel}:{n}: imports {mod}, banned in the execution package")
            continue
        if mod in NETWORK_HELPERS or mod.startswith("urllib.parse."):
            continue
        if top == "edge_lab":
            parts = mod.split(".")
            if len(parts) == 1 or parts[1] == "execution":
                continue  # bare "edge_lab" from `from .. import x` (its "edge_lab.x" entry is judged), or own modules
            if parts[1] in PROTECTED or parts[1] not in ALLOWED_OWNERS:
                hits.append(f"{rel}:{n}: imports edge_lab.{parts[1]}, not an allowed owner")
        elif top in THIRD_PARTY:
            if rel not in THIRD_PARTY[top]:
                hits.append(f"{rel}:{n}: imports {top} outside {sorted(THIRD_PARTY[top])}")
        elif top in BANNED_IN_PACKAGE:
            hits.append(f"{rel}:{n}: imports {top}, banned in the execution package")
        elif top in NETWORK_MODULES and rel not in NETWORK_FILES:
            hits.append(f"{rel}:{n}: imports network module {top} outside {sorted(NETWORK_FILES)}")
        elif top == "sqlite3" and rel not in SQLITE_FILES:
            hits.append(f"{rel}:{n}: imports sqlite3 outside {sorted(SQLITE_FILES)}")
        elif top not in stdlib and top != "__future__":
            hits.append(f"{rel}:{n}: imports third-party {top}")
    hits += [f"{rel}:{n}: banned call or environment access" for n, line in enumerate(text.splitlines(), 1)
             if _BANNED_CALLS.search(line)]
    return hits


def _outside_files():
    files = []
    for base in OUTSIDE_DIRS:
        if base.is_dir():
            files += [p for p in base.rglob("*.py") if PACKAGE not in p.parents]
    return sorted(files)


def test_the_package_exists_and_the_scans_are_not_vacuous():
    assert (PACKAGE / "__init__.py").is_file() and (PACKAGE / "model.py").is_file()
    outside = _outside_files()
    assert len([p for p in outside if SRC in p.parents]) > 50
    assert any((ROOT / "scripts") in p.parents for p in outside) and any((ROOT / "deploy") in p.parents for p in outside)


def test_nothing_outside_the_package_reaches_it():
    hits = [h for p in _outside_files() for h in _outside_violations(_rel(p), p.read_text(encoding="utf-8"))]
    assert not hits, "\n".join(hits)


@pytest.mark.parametrize("rel,line", [
    ("edge_lab/cli.py", "from .execution import model"),
    ("edge_lab/cli.py", "from . import execution"),
    ("edge_lab/cli.py", "from edge_lab import execution as x"),
    ("edge_lab/risk.py", "import edge_lab.execution.signer"),
    ("edge_lab/dashboard/app.py", "from ..execution.transport import send"),
    ("edge_lab/dashboard/views/research.py", "from ...execution import journal"),
    ("edge_lab/daily.py", "mod = importlib.import_module('edge_lab.execution.transport')"),
    ("edge_lab/daily.py", "from importlib import import_module as im; im('edge_lab.' + 'execution.signer')"),
    ("edge_lab/daily.py", "runpy.run_module('edge_lab.execution.transport')"),
    ("edge_lab/daily.py", "pkgutil.resolve_name('edge_lab.execution.signer:Signer')"),
    ("edge_lab/daily.py", "m = sys.modules['edge_lab.execution']"),
    ("edge_lab/daily.py", "import edge_lab\nx = edge_lab.execution"),
    ("edge_lab/daily.py", "from . import execution_ticket; import edge_lab.execution"),
    ("edge_lab/daily.py", "p = f'edge_lab.{name}'"),
    ("edge_lab/daily.py", "p = 'src/edge_lab/execution/signer.py'"),
    ("edge_lab/daily.py", "importlib.import_module('.execution', 'edge_lab')"),
    ("edge_lab/daily.py", "__import__('edge_lab', fromlist=['execution'])"),
    ("edge_lab/daily.py", "p = 'edge_lab' + '.' + 'execution'"),
    ("edge_lab/daily.py", "p = 'edge_lab.%s' % name"),
    ("edge_lab/daily.py", "p = 'edge_lab.{}'.format(name)"),
    ("edge_lab/daily.py", "p = '.'.join(['edge_lab', 'execution'])"),
    ("scripts/x.py", "from edge_lab.execution import transport"),
])
def test_an_outside_reach_is_caught(rel, line):
    assert _outside_violations(rel, line + "\n"), line


def test_ordinary_outside_code_passes():
    ok = ('"""Docs may mention src/edge_lab/execution/ (ADR 0043)."""\n'
          "from . import execution_ticket\nRESEARCH = 'edge_lab.sizing_counterfactual'\nx = cfg['execution']\n"
          "y = view.execution\nimport importlib\nm = importlib.import_module(RESEARCH)\nz = 'execution.status'\n"
          "w = ', '.join(['a', 'b'])\nv = '{} {}'.format(a, b)\n")
    assert not _outside_violations("edge_lab/dashboard/data.py", ok)


def test_the_package_imports_only_what_its_files_may():
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
    ("edge_lab/execution/journal.py", "import http.client"),
    ("edge_lab/execution/journal.py", "import socket"),
    ("edge_lab/execution/journal.py", "from urllib.request import urlopen"),
    ("edge_lab/execution/lifecycle.py", "import sqlite3"),
    ("edge_lab/execution/journal.py", "import subprocess"),
    ("edge_lab/execution/transport.py", "import importlib"),
    ("edge_lab/execution/journal.py", "import os\nos.system('x')"),
    ("edge_lab/execution/model.py", "import os\nk = os.environ['X']"),
    ("edge_lab/execution/model.py", "import os\nk = os.getenv('X')"),
    ("edge_lab/execution/model.py", "import pickle"),
    ("edge_lab/execution/journal.py", "from os import system"),
    ("edge_lab/execution/journal.py", "from os import environ"),
    ("edge_lab/execution/journal.py", "import os\nos.posix_spawn(p, a, e)"),
    ("edge_lab/execution/journal.py", "from concurrent.futures import ProcessPoolExecutor"),
    ("edge_lab/execution/kalshi_wire.py", "from urllib.request import urlopen"),
    ("edge_lab/execution/kalshi_wire.py", "from http import client"),
])
def test_a_forbidden_package_import_is_caught(rel, line):
    assert _inside_violations(rel, line + "\n"), line


def test_allowed_imports_pass():
    assert not _inside_violations("edge_lab/execution/risk_gate.py", "from .. import risk\nfrom ..risk import RiskPolicy\n"
                                  "from .model import OrderIntent\nfrom decimal import Decimal\n")
    assert not _inside_violations("edge_lab/execution/signer.py",
                                  "from cryptography.hazmat.primitives.asymmetric import ed25519\n")
    assert not _inside_violations("edge_lab/execution/transport.py", "from urllib.request import Request\nimport ssl\n")
    assert not _inside_violations("edge_lab/execution/journal.py", "import sqlite3\nimport os\nos.fsync(fd)\n")
    assert not _inside_violations("edge_lab/execution/kalshi_wire.py", "from urllib.parse import urlencode, quote\n"
                                  "from http import HTTPStatus\nimport urllib.parse\n")


def test_protected_owners_are_never_allowed():
    assert not ALLOWED_OWNERS & PROTECTED


def test_allowed_owners_reach_no_protected_module_except_the_pinned_edge():
    """The transitive closure of every allowed owner, edges recorded, against PROTECTED."""
    reached: dict[str, tuple[str, str]] = {}
    for owner in ALLOWED_OWNERS:
        stack, seen = [owner], {owner}
        while stack:
            mod = stack.pop()
            for dep in _owner_deps(mod):
                if dep in PROTECTED:
                    reached.setdefault(dep, (mod, dep))
                    continue  # do not walk through a protected module: the edge itself is the finding
                if dep not in seen:
                    seen.add(dep)
                    stack.append(dep)
    edges = set(reached.values())
    assert edges == set(TRANSITIVE_EXEMPT), f"unexpected protected reach: {sorted(edges - set(TRANSITIVE_EXEMPT))}"
    # The exempt edge itself leads nowhere protected (shadow_ledger does not reach the research store).
    assert not _owner_deps("shadow_ledger") & PROTECTED


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
