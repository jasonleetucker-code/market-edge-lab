"""EXP-001's frozen specification pins files outside experiment.toml by SHA-256.

The preregistration freezes the manifest's fields. The spec also depends on the dataset,
the design document and the fee/statistics code, so the frozen text names them as
`path sha256=<hex>` and this test fails if any of them changes. Changing one means a new
experiment (or an explicit, reviewed change to this pin), never a silent edit.
"""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "experiments" / "EXP-001-kxhighny-nws-vs-market"
PIN = re.compile(r"([\w./-]+) sha256=([0-9a-f]{64})")


def _digest(path: Path) -> str:
    # Universal newlines, so a CRLF checkout hashes like the committed LF bytes.
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def _pins():
    baseline = json.loads((EXP / "preregistration.json").read_text())
    text = json.dumps(baseline["frozen_fields"], ensure_ascii=False)
    return PIN.findall(text)


def test_frozen_spec_pins_dataset_design_and_code():
    paths = {p for p, _ in _pins()}
    assert "experiments/EXP-001-kxhighny-nws-vs-market/gate3/dataset.csv" in paths
    assert "experiments/EXP-001-kxhighny-nws-vs-market/gate3/DESIGN.md" in paths
    assert {"src/edge_lab/fees.py", "src/edge_lab/stats.py"} <= paths


def test_pinned_files_are_unchanged():
    changed = [p for p, h in _pins() if _digest(ROOT / p) != h]
    assert not changed, f"frozen EXP-001 artifacts changed: {changed}"


def test_dataset_manifest_matches_the_frozen_dataset_hash():
    manifest = json.loads((EXP / "gate3" / "dataset_manifest.json").read_text())
    pinned = dict(_pins())["experiments/EXP-001-kxhighny-nws-vs-market/gate3/dataset.csv"]
    assert manifest["dataset_sha256"] == pinned
