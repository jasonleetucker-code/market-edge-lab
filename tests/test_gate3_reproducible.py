"""The committed EXP-001 dataset, manifest, quality report and train-only description are
exactly what the versioned code produces from the committed evidence (no network)."""

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE3 = ROOT / "experiments" / "EXP-001-kxhighny-nws-vs-market" / "gate3"


def _h(text):
    # Compare digests: pytest's diff of multi-megabyte strings is extremely slow.
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dataset_rebuilds_byte_identically_twice():
    builder = _load("build_exp001_dataset")
    first, second = builder.build(), builder.build()
    assert {k: _h(v) for k, v in first.items()} == {k: _h(v) for k, v in second.items()}
    for name, content in first.items():
        assert _h((GATE3 / name).read_text(encoding="utf-8")) == _h(content), f"{name} is stale; run scripts/build_exp001_dataset.py"


def test_manifest_hashes_every_input_file():
    builder = _load("build_exp001_dataset")
    manifest = json.loads((GATE3 / "dataset_manifest.json").read_text(encoding="utf-8"))
    expected = {p.relative_to(ROOT).as_posix() for p in builder.input_files()}
    assert set(manifest["input_sha256"]) == expected
    assert any("pfm_extracts_" in k for k in expected) and any("iem_clinyc_" in k for k in expected)


def test_descriptive_report_is_current_and_train_only():
    describer = _load("describe_exp001_train")
    assert _h((GATE3 / "DESCRIPTIVE_TRAIN.md").read_text(encoding="utf-8")) == _h(describer.build())
    rows = describer.train_rows((GATE3 / "dataset.csv").read_text(encoding="utf-8"))
    assert rows and {r["split"] for r in rows} == {"train"}
