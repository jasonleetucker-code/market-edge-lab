"""No credentials in tracked files."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PATTERNS = {
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "OpenAI/Anthropic-style key": re.compile(r"\bsk-(ant-)?[A-Za-z0-9_-]{24,}\b"),
    "Slack token": re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b"),
    "assigned secret": re.compile(
        r"""(?i)\b(api[_-]?key|secret|password|access[_-]?token)\b\s*[:=]\s*["'][^"'\s]{12,}["']"""
    ),
}


def _tracked_files():
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        out = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [ROOT / f for f in out]


def test_no_secret_patterns_in_tracked_files():
    this_file = Path(__file__).resolve()
    hits = []
    for path in _tracked_files():
        if path.resolve() == this_file or not path.is_file():
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        for label, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                hits.append(f"{path.relative_to(ROOT)}: {label}: {match.group(0)[:12]}…")
    assert not hits, "possible secrets:\n" + "\n".join(hits)


def test_env_files_are_ignored():
    gitignore = (ROOT / ".gitignore").read_text().splitlines()
    assert ".env" in gitignore and "!.env.example" in gitignore
