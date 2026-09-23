"""Third-party code and dependencies are traceable (docs/GITHUB_REUSE_AUDIT.md, adoption rules).

Public GitHub is not public domain. Any code copied, vendored, ported or adapted from
another project, and any runtime dependency, must have an entry in THIRD_PARTY_NOTICES.md
that pins the upstream commit and names its license. First-party sources (the owner's own
repositories) are listed there too, so the check never has to guess.
"""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
CODE_DIRS = (ROOT / "src", ROOT / "tests", ROOT / "scripts")

ENTRY = re.compile(r"^### (TPN-[A-Z]?\d{3})\b", re.M)
REFERENCE = re.compile(r"\bTPN-[A-Z]?\d{3}\b")
MARKER = re.compile(r"\b(copied|vendored|ported|adapted|borrowed)\s+from\b", re.I)
# "copied from the fill" is internal; "adapted from the nautilus repo" is not. A marker needs a
# citation when the next word is not an article/pronoun, or when the nearby text names an
# outside source.
INTERNAL_START = re.compile(r"\s+(the|a|an|this|that|these|those|it|its|each|every|our|one|another)\b", re.I)
OUTSIDE_WORDS = (r"github|gitlab|\brepo|repositor|project|library|package|upstream|open[- ]source|\bsdk\b|"
                 r"\bpypi\b|\bnpm\b|https?://|codebase")
PINS = ROOT / "docs" / "audits" / "2026-09-23-github-reuse" / "deep_review_pins.tsv"


def _audited_names() -> list[str]:
    """Owner and repository names of every audited project, e.g. "ccxt", "nautilus_trader"."""
    names: set[str] = set()
    for line in PINS.read_text(encoding="utf-8").splitlines()[1:]:
        owner, _, repo = line.split("\t", 1)[0].partition("/")
        names |= {n.lower() for n in (owner, repo) if len(n) >= 4}
    # Venue names and plain words also name our own code and data ("copied from the kalshi
    # payload"), so they are not evidence of an outside source.
    names -= {"kalshi", "polymarket", "agents", "brier", "examples"}
    return sorted(names, key=len, reverse=True)


OUTSIDE = re.compile(OUTSIDE_WORDS + "|" + "|".join(rf"\b{re.escape(n)}" for n in _audited_names()), re.I)
GITHUB = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
SHA = re.compile(r"\b[0-9a-f]{40}\b")
SPDX = re.compile(r"^- \*\*License:\*\* \S", re.M)


def _needs_citation(after_marker: str) -> bool:
    return not INTERNAL_START.match(after_marker) or bool(OUTSIDE.search(after_marker))


def test_marker_rules_on_examples():
    def needs(phrase: str) -> bool:
        match = MARKER.search(phrase)
        return bool(match) and _needs_citation(phrase[match.end():])

    assert needs("Adapted from the nautilus_trader repo")
    assert needs("ported from ccxt's kalshi.ts")
    assert needs("Vendored from https://example.org/lib")
    assert needs("copied from the upstream project")
    assert needs("Adapted from Brisket's online-backup pattern")  # cited as first party elsewhere
    assert needs("adapted from the nautilus_trader codebase")
    assert needs("copied from the ccxt kalshi adapter")
    assert needs("ported from the approach in Hummingbot")
    assert not needs("fee fields copied from the fill")
    assert not needs("fields copied from the kalshi payload")
    assert not needs("status is derived from what was fetched")


def _notices() -> str:
    return NOTICES.read_text(encoding="utf-8")


def _entries() -> dict[str, str]:
    text = _notices()
    heads = list(ENTRY.finditer(text))
    return {m.group(1): text[m.start(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
            for i, m in enumerate(heads)}


def _first_party() -> set[str]:
    section = _notices().split("## First-party sources", 1)[1].split("\n## ", 1)[0]
    return {name.lower() for name in re.findall(r"^- `([^`]+)`", section, re.M)}


def _code_files():
    files = [p for d in CODE_DIRS for p in d.rglob("*.py") if "__pycache__" not in p.parts]
    return [p for p in files if p.resolve() != Path(__file__).resolve()]


def test_notices_file_exists_and_is_structured():
    text = _notices()
    for heading in ("## Runtime dependencies", "## Vendored or copied source", "## First-party sources",
                    "## Independently reimplemented patterns"):
        assert heading in text, heading
    assert _code_files(), "no code scanned; the checks below would pass vacuously"


def test_every_entry_pins_an_upstream_commit_and_a_license():
    entries = _entries()
    for entry_id, body in entries.items():
        assert SHA.search(body), f"{entry_id} does not pin a 40-hex upstream commit"
        assert SPDX.search(body), f"{entry_id} does not name a license"


def test_every_runtime_dependency_is_recorded():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    section = _notices().split("## Runtime dependencies", 1)[1].split("\n## ", 1)[0]
    for requirement in project.get("dependencies", []):
        name = re.split(r"[<>=!~\[; ]", requirement, 1)[0].strip().lower()
        assert f"`{name}`" in section.lower(), f"runtime dependency {name!r} has no notice entry and reason"


def test_copy_markers_cite_a_notice_or_a_first_party_source():
    entries, first_party = _entries(), _first_party()
    problems = []
    for path in _code_files():
        text = path.read_text(encoding="utf-8")
        for match in MARKER.finditer(text):
            window = text[match.start(): match.start() + 200].lower()
            if not _needs_citation(text[match.end(): match.end() + 120]):
                continue
            cited = [r for r in REFERENCE.findall(text[match.start(): match.start() + 200]) if r in entries]
            if not cited and not any(name in window for name in first_party):
                line = text.count("\n", 0, match.start()) + 1
                problems.append(f"{path.relative_to(ROOT)}:{line}")
    assert not problems, "copy/adapt markers without a THIRD_PARTY_NOTICES.md entry:\n" + "\n".join(problems)


def test_every_notice_reference_exists():
    entries = _entries()
    missing = sorted({f"{p.relative_to(ROOT)}: {ref}" for p in _code_files()
                      for ref in REFERENCE.findall(p.read_text(encoding="utf-8")) if ref not in entries})
    assert not missing, "references to unknown notice entries:\n" + "\n".join(missing)


def test_third_party_github_urls_in_runtime_code_are_recorded():
    notices, first_party = _notices().lower(), _first_party()
    problems = []
    files = [p for d in (ROOT / "src", ROOT / "scripts") for pattern in ("*.py", "*.sh") for p in d.rglob(pattern)]
    assert files
    for path in files:
        for owner, repo in GITHUB.findall(path.read_text(encoding="utf-8")):
            slug = f"{owner}/{repo}".lower().removesuffix(".git")
            if owner.lower() not in first_party and slug not in first_party and slug not in notices:
                problems.append(f"{path.relative_to(ROOT)}: {slug}")
    assert not problems, "third-party repositories referenced without a notice entry:\n" + "\n".join(problems)
