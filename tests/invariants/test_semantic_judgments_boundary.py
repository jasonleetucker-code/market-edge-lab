"""The semantic-triage module stays a value-type layer with no capability (#181 Deliverable F, ADR 0049).

`src/edge_lab/semantic_judgments.py` may not import, name or reach credentials, the signer, the execution package,
sizing, fee authority, risk configuration, grants, the wallet package, the network or the environment. It makes no
model call: there is no provider SDK, no network module and no pinned hosted model version.

Static rules, in the pattern of `test_execution_boundary.py` and `tests/wallet/test_wallet_boundary.py`:
- **Import allowlist.** Standard-library modules from `ALLOWED_STDLIB` only, and from `edge_lab` only
  `ALLOWED_OWNERS` (content hashing). Every other import, in any form, is a violation.
- **Transitive.** Each allowed owner, followed through its own `edge_lab` imports, obeys the same allowlist.
- **Banned names.** No identifier (name, attribute, function, class, argument, keyword, import alias) and no
  non-docstring string constant matches `BANNED_NAME`, and no dynamic import, eval/exec, file open or environment
  access appears.
- **Runtime.** Importing the module in a fresh interpreter loads no network module and no `edge_lab` module beyond
  the allowlist.

Every rule is mutation-checked: a probe that breaks it must be caught. Static scans catch ordinary and careless paths,
not determined obfuscation; review is the other control.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
MODULE = SRC / "edge_lab" / "semantic_judgments.py"
REL = "edge_lab/semantic_judgments.py"

ALLOWED_STDLIB = frozenset({"__future__", "dataclasses", "datetime", "decimal", "enum", "json", "math", "re", "types",
                            "typing"})
ALLOWED_OWNERS = frozenset({"provenance"})
# What an allowed owner may import itself (provenance hashes with hashlib).
OWNER_STDLIB = ALLOWED_STDLIB | {"hashlib"}

BANNED_NAME = re.compile(
    r"(?i)credential|secret|password|api_?key|access_?key|private_?key|signer|signing|sign_request|signature"
    r"|execution|order_?intent|place_?order|submit_?order|cancel_?order|orderbook"
    r"|sizing|kelly|position_?size|stake|fee_?schedule|fee_?authority|fee_?rate"
    r"|risk_?(limit|polic|config|gate|account)|grant|wallet|shadow_?ledger|ledger"
    r"|getenv|environ|subprocess|socket|urlopen|transport|http_?client"
    r"|edge_lab\.(?!provenance\b)")
_DYNAMIC = re.compile(r"__import__\s*\(|\beval\s*\(|\bexec\s*\(|(?<![.\w])compile\s*\(|\bopen\s*\(|\bimport_module\b"
                      r"|\bsys\s*\.\s*modules\b|\bglobals\s*\(|\bgetattr\s*\(")


def _imports(text: str, rel: str) -> list[tuple[int, str]]:
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
            out += [(node.lineno, f"{mod}.{a.name}") for a in node.names]  # `from . import fee_schedules`
    return out


def import_violations(text: str, rel: str = REL, stdlib: frozenset[str] = ALLOWED_STDLIB) -> list[str]:
    hits = []
    for line, mod in _imports(text, rel):
        parts = mod.split(".")
        if parts[0] == "edge_lab":
            if len(parts) == 1:
                continue  # `from .. import x` also yields "edge_lab.x", judged on its own
            if parts[1] not in ALLOWED_OWNERS:
                hits.append(f"{rel}:{line}: imports edge_lab.{parts[1]}, not an allowed owner")
            elif len(parts) > 3:
                hits.append(f"{rel}:{line}: reaches inside {mod}")
        elif parts[0] not in stdlib:
            hits.append(f"{rel}:{line}: imports {mod}, outside the allowlist")
    return hits


def name_violations(text: str, rel: str = REL) -> list[str]:
    tree = ast.parse(text)
    docstrings = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    hits = []

    def check(value: str, line: int, what: str) -> None:
        if BANNED_NAME.search(value):
            hits.append(f"{rel}:{line}: {what} {value!r} names a capability")

    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Name):
            check(node.id, line, "name")
        elif isinstance(node, ast.Attribute):
            check(node.attr, line, "attribute")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            check(node.name, line, "definition")
        elif isinstance(node, ast.arg):
            check(node.arg, line, "argument")
        elif isinstance(node, ast.keyword) and node.arg:
            check(node.arg, line, "keyword")
        elif isinstance(node, ast.alias):
            check(node.name, line, "import")
            if node.asname:
                check(node.asname, line, "import alias")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            check(node.value, line, "string")
    for n, src_line in enumerate(text.splitlines(), 1):
        if _DYNAMIC.search(src_line.split("#", 1)[0]):
            hits.append(f"{rel}:{n}: dynamic import, eval/exec, file open or reflection")
    return hits


def _owner_text(owner: str) -> str | None:
    path = SRC / "edge_lab" / f"{owner}.py"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def transitive_violations(text: str, read_owner=_owner_text) -> list[str]:  # type: ignore[no-untyped-def]
    hits, seen = [], set()
    todo = sorted({m.split(".")[1] for _, m in _imports(text, REL)
                   if m.startswith("edge_lab.") and len(m.split(".")) >= 2})
    while todo:
        owner = todo.pop()
        if owner in seen:
            continue
        seen.add(owner)
        if owner not in ALLOWED_OWNERS:
            hits.append(f"reaches edge_lab.{owner}")
            continue
        owner_src = read_owner(owner)
        if owner_src is None:
            hits.append(f"edge_lab.{owner} is missing")
            continue
        rel = f"edge_lab/{owner}.py"
        hits += import_violations(owner_src, rel, OWNER_STDLIB)
        hits += [h for h in name_violations(owner_src, rel) if "dynamic" in h]
        todo += sorted({m.split(".")[1] for _, m in _imports(owner_src, rel)
                        if m.startswith("edge_lab.") and len(m.split(".")) >= 2} - seen)
    return hits


def test_the_module_exists_and_the_scan_is_not_vacuous():
    text = MODULE.read_text(encoding="utf-8")
    assert len(_imports(text, REL)) >= 10
    assert any(m == "edge_lab.provenance" for _, m in _imports(text, REL))


def test_the_module_imports_only_its_allowlist():
    hits = import_violations(MODULE.read_text(encoding="utf-8"))
    assert not hits, "\n".join(hits)


def test_the_module_names_no_capability():
    hits = name_violations(MODULE.read_text(encoding="utf-8"))
    assert not hits, "\n".join(hits)


def test_allowed_owners_reach_nothing_else():
    hits = transitive_violations(MODULE.read_text(encoding="utf-8"))
    assert not hits, "\n".join(hits)


def test_importing_the_module_loads_no_network_provider_or_other_edge_lab_module():
    code = ("import sys\nimport edge_lab.semantic_judgments\n"
            "net = ('socket', '_socket', 'ssl', '_ssl', 'http', 'http.client', 'urllib.request', 'requests', 'httpx',\n"
            "       'asyncio', 'anthropic', 'openai', 'subprocess')\n"
            "bad = sorted(m for m in sys.modules if m in net or (m.startswith('edge_lab') and m not in\n"
            "    ('edge_lab', 'edge_lab.provenance', 'edge_lab.semantic_judgments')))\n"
            "print(','.join(bad))\n")
    env = {"PYTHONPATH": str(SRC), "PATH": os.environ.get("PATH", "")}
    if os.environ.get("SYSTEMROOT"):
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]  # Windows needs it to start an interpreter
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "", f"loaded: {proc.stdout.strip()}"


def test_no_hosted_model_can_be_addressed():
    """Zero model calls, structurally: no hosted provider has a pinned version, so no request to one validates,
    and every result is FIXTURE."""
    from edge_lab import semantic_judgments as sj

    hosted = {p for p in sj.Provider if sj._PROVIDER_COST_KIND[p] is sj.CostKind.PROVIDER_METERED}
    assert hosted == {sj.Provider.JEV, sj.Provider.KEV}
    assert all(sj.PINNED_MODEL_VERSIONS[p] == frozenset() for p in hosted)
    assert sj.RESULT_EVIDENCE_CLASS is sj.EvidenceClass.FIXTURE


@pytest.mark.parametrize("probe", [
    "from .execution import model",
    "from .execution.signer import Signer",
    "import edge_lab.execution",
    "from . import fee_schedules",
    "from .fee_schedules import FeeSchedule",
    "from .sizing_v2 import size",
    "from . import risk",
    "from .execution_ticket import TicketLimits",
    "from .sources import REGISTRY",
    "from . import odds_api",
    "from . import secrets_file",
    "from .wallet_intel import selection",
    "from . import storage",
    "from .provenance.deep import x",
    "import os",
    "from os import environ",
    "import socket",
    "from urllib.request import urlopen",
    "import urllib.parse",
    "import http.client",
    "import importlib",
    "import subprocess",
    "import pathlib",
    "import hashlib",
    "import anthropic",
    "import openai",
    "import requests",
])
def test_a_forbidden_import_is_caught(probe):
    assert import_violations(probe + "\n"), probe


@pytest.mark.parametrize("probe", [
    "credential = None",
    "api_key = load()",
    "def place_order(x): pass",
    "class Signer: pass",
    "x.signer.sign(b)",
    "def f(position_size): pass",
    "f(stake=1)",
    "risk_limit = 5",
    "RiskPolicy = None",
    "grant_id = 'g'",
    "wallet = w",
    "fee_schedule = s",
    "kelly = 0.1",
    "s = 'edge_lab.execution.transport'",
    "s = 'edge_lab.fee_schedules'",
    "x = os.environ",
    "m = __import__('socket')",
    "eval('1')",
    "exec('x = 1')",
    "f = open('keys.txt')",
    "m = sys.modules['x']",
    "v = getattr(obj, name)",
    "from importlib import import_module as im",
    "code = compile('x = 1', 'f', 'exec')",
])
def test_a_banned_name_is_caught(probe):
    assert name_violations(probe + "\n"), probe


@pytest.mark.parametrize("clean", [
    "from .provenance import payload_sha256, sha256_hex",
    "from decimal import Decimal\nimport json, math, re",
    '"""Docstrings may say execution, credentials, fees and sizing are out of reach."""\nx = 1',
    "label = 'CONTRADICTION_NEEDS_HUMAN'\nreason = 'never settlement verification'",
    "s = 'edge_lab.provenance'",
    "import re\nP = re.compile('[a-z]+')",
])
def test_clean_code_passes(clean):
    assert import_violations(clean + "\n") == [] and name_violations(clean + "\n") == []


def test_transitive_probes_are_caught():
    module = "from .provenance import payload_sha256\n"
    assert transitive_violations(module) == []
    fakes = {"provenance": "from . import fee_schedules\n"}
    assert any("fee_schedules" in h for h in transitive_violations(module, read_owner=fakes.get))
    fakes = {"provenance": "import socket\n"}
    assert any("socket" in h for h in transitive_violations(module, read_owner=fakes.get))
    fakes = {"provenance": "import hashlib\nm = __import__('os')\n"}
    assert any("dynamic" in h for h in transitive_violations(module, read_owner=fakes.get))
    assert transitive_violations("from .storage import x\n") == ["reaches edge_lab.storage"]
