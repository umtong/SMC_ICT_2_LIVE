from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import importlib.util
import json
import py_compile
import sys

ROOT = Path(__file__).parents[1]
BUNDLE = ROOT / "research/experiments/crossvenue_forward_evidence/source-bundle.tar.gz"
EXTRACTOR = ROOT / "research/experiments/crossvenue_forward_evidence/extract_bundle.py"
EXPECTED = "ebd83c20abaf6bf3ab7c9c467e63bd1d1129db813ddad9fa2fd3fdcca5ffcaa2"


def _load_extractor():
    spec = importlib.util.spec_from_file_location("crossvenue_forward_extract", EXTRACTOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_source_bundle_integrity_and_compilation(tmp_path: Path):
    assert sha256(BUNDLE.read_bytes()).hexdigest() == EXPECTED
    module = _load_extractor()
    destination = tmp_path / "source"
    module.safe_extract(BUNDLE, destination)
    manifest = json.loads((destination / "FILE_MANIFEST.json").read_text(encoding="utf-8"))
    paths = {row["path"] for row in manifest["files"]}
    assert "research/experiments/forward_execution_capture/capture.py" in paths
    assert "research/experiments/forward_execution_capture/ledger.py" in paths
    assert "research/experiments/forward_execution_capture/shadow_replay.py" in paths
    assert "research/experiments/crossvenue_liquidation_recovery/event_mechanism_screen.py" in paths
    assert "tests/test_forward_capture.py" in paths
    for path in destination.rglob("*.py"):
        py_compile.compile(str(path), doraise=True)
