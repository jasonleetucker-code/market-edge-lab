"""The wallet-intelligence package stays offline, stdlib-only and away from execution (ADR 0045).

Static rules over every file in `src/edge_lab/wallet_intel/`:
- no network module: socket, ssl, http (any submodule), urllib (any submodule but `parse`), asyncio,
  `edge_lab.http`, `requests` or any other third-party package;
- no `edge_lab.execution`, no research store (`storage`), no `shadow_ledger`, no protected-label
  owner, and no `research_economics` (it imports the experiment registry);
- no environment reads (`os.environ`, `getenv`), no process or dynamic import (`subprocess`,
  `importlib`, `__import__`, `eval`, `exec`);
- the `edge_lab` modules it imports, followed transitively, reach none of the above.

A runtime check imports the package in a fresh interpreter and asserts that no network or execution
module was loaded. Every static rule is mutation-checked: a probe that breaks it must be caught.
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
PACKAGE = SRC / "edge_lab" / "wallet_intel"

NETWORK_TOP = frozenset({"socket", "_socket", "ssl", "_ssl", "http", "asyncio", "selectors", "socketserver",
                         "ftplib", "smtplib", "poplib", "imaplib", "telnetlib", "xmlrpc", "webbrowser", "email",
                         "wsgiref", "nntplib", "requests", "urllib3", "httpx", "aiohttp"})
BANNED_TOP = frozenset({"subprocess", "multiprocessing", "importlib", "runpy", "pkgutil", "ctypes", "pickle",
                        "shelve", "marshal", "sqlite3"})
FORBIDDEN_OWNERS = frozenset({"execution", "http", "storage", "shadow_ledger", "research_economics",
                              "sports_evidence", "exp002_timing", "odds_schedule", "price_observations",
                              "odds_consensus", "experiments", "settlement", "forward", "exp001_baseline",
                              "exp001_shadow", "exp001_stageb", "dataset_exp001", "describe_exp001"})
_ENV_OR_DYNAMIC = re.compile(r"\bos\s*\.\s*(environ|getenv|putenv|system|popen|spawn\w*|exec\w*)\b|\bgetenv\s*\(|"
                             r"__import__\s*\(|\beval\s*\(|\bexec\s*\(|\benviron\b")


def _imports(text: str, rel: str) -> list[str]:
    parts = rel.removesuffix(".py").split("/")[:-1]
    out = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = parts[: len(parts) - (node.level - 1)]
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            out.append(mod)
            out += [f"{mod}.{a.name}" for a in node.names]
    return out


def violations(text: str, rel: str = "edge_lab/wallet_intel/probe.py") -> list[str]:
    hits = []
    stdlib = sys.stdlib_module_names
    for mod in _imports(text, rel):
        top = mod.split(".")[0]
        if mod == "urllib.parse" or mod.startswith("urllib.parse."):
            continue
        if top == "urllib" and mod in ("urllib",):
            hits.append(f"binds the urllib package: {mod}")
        elif top == "urllib":
            hits.append(f"network module {mod}")
        elif top in NETWORK_TOP:
            hits.append(f"network module {mod}")
        elif top in BANNED_TOP:
            hits.append(f"banned module {mod}")
        elif top == "os" and len(mod.split(".")) > 1 and re.fullmatch(r"environ\w*|getenv|putenv|system|popen",
                                                                       mod.split(".")[1]):
            hits.append(f"environment or process access {mod}")
        elif top == "edge_lab":
            pieces = mod.split(".")
            if len(pieces) >= 2 and pieces[1] in FORBIDDEN_OWNERS:
                hits.append(f"forbidden owner {mod}")
        elif top not in stdlib and top != "__future__":
            hits.append(f"third-party {mod}")
    for n, line in enumerate(text.splitlines(), 1):
        if _ENV_OR_DYNAMIC.search(line):
            hits.append(f"line {n}: environment read or dynamic code")
    return hits


def _files() -> list[Path]:
    files = sorted(PACKAGE.rglob("*.py"))
    assert files, "the wallet_intel package is missing"
    return files


def test_package_files_have_no_network_execution_env_or_third_party_imports():
    hits = []
    for path in _files():
        rel = path.relative_to(SRC).as_posix()
        hits += [f"{rel}: {h}" for h in violations(path.read_text(encoding="utf-8"), rel)]
    assert not hits, "\n".join(hits)


def _owner_imports(owner: str) -> set[str]:
    path = SRC / "edge_lab" / f"{owner}.py"
    if not path.is_file():
        return set()
    return {m.split(".")[1] for m in _imports(path.read_text(encoding="utf-8"), f"edge_lab/{owner}.py")
            if m.startswith("edge_lab.") and len(m.split(".")) >= 2}


def test_transitive_edge_lab_imports_reach_no_forbidden_owner_or_network_module():
    direct = set()
    for path in _files():
        for mod in _imports(path.read_text(encoding="utf-8"), path.relative_to(SRC).as_posix()):
            pieces = mod.split(".")
            if pieces[0] == "edge_lab" and len(pieces) >= 2 and pieces[1] != "wallet_intel":
                direct.add(pieces[1])
    seen, todo = set(), list(direct)
    while todo:
        owner = todo.pop()
        if owner in seen:
            continue
        seen.add(owner)
        todo += sorted(_owner_imports(owner) - seen)
    assert not (seen & FORBIDDEN_OWNERS), sorted(seen & FORBIDDEN_OWNERS)
    for owner in seen:
        path = SRC / "edge_lab" / f"{owner}.py"
        if path.is_file():
            hits = [h for h in violations(path.read_text(encoding="utf-8"), f"edge_lab/{owner}.py")
                    if h.startswith("network") or h.startswith("binds") or h.startswith("third-party")]
            assert not hits, f"{owner}: {hits}"


def test_importing_the_package_loads_no_network_or_execution_module():
    code = (
        "import sys\n"
        "import edge_lab.wallet_intel as w\n"
        "import pkgutil, importlib\n"
        "for m in pkgutil.iter_modules(w.__path__):\n"
        "    importlib.import_module('edge_lab.wallet_intel.' + m.name)\n"
        "bad = sorted(m for m in sys.modules if m in ('socket', '_socket', 'ssl', '_ssl', 'http.client',\n"
        "    'urllib.request', 'requests', 'edge_lab.http', 'asyncio') or m.startswith('edge_lab.execution')\n"
        "    or m in ('edge_lab.storage', 'edge_lab.shadow_ledger', 'edge_lab.experiments',\n"
        "    'edge_lab.research_economics'))\n"
        "print(','.join(bad))\n"
    )
    env = {"PYTHONPATH": str(SRC), "PATH": os.environ.get("PATH", "")}
    if os.environ.get("SYSTEMROOT"):
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]  # Windows needs it to start an interpreter
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "", f"loaded: {proc.stdout.strip()}"


@pytest.mark.parametrize("probe", [
    "import socket",
    "import ssl",
    "import http.client",
    "from http import client",
    "import urllib.request",
    "from urllib import request",
    "import urllib",
    "import requests",
    "import asyncio",
    "from edge_lab import http",
    "from ..http import get_json",
    "from .. import http",
    "from ..execution import model",
    "from edge_lab.execution.model import OrderIntent",
    "import edge_lab.execution",
    "from .. import storage",
    "from ..shadow_ledger import AccountState",
    "from ..research_economics import Labeled",
    "from ..experiments import REGISTRY",
    "from ..sports_evidence import x",
    "import os\nx = os.environ['K']",
    "import os\nx = os.getenv('K')",
    "from os import environ",
    "from os import getenv",
    "import subprocess",
    "import importlib",
    "m = __import__('socket')",
    "eval('1')",
    "import numpy",
])
def test_probes_are_caught(probe):
    assert violations(probe), probe


@pytest.mark.parametrize("clean", [
    "from decimal import Decimal",
    "from ..provenance import canonical_json",
    "from ..opportunity import DepthLevel",
    "from ..sources import AccessTier",
    "from .events import Action",
    "from urllib.parse import urlparse",
    "import json, math, random",
])
def test_clean_code_passes(clean):
    assert violations(clean) == []
