from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_caption_parsers() -> None:
    module = load("harvest_transcripts", ROOT / "harvest_transcripts.py")
    module.self_test()


def test_concept_index_patterns() -> None:
    module = load("build_concept_index", ROOT / "build_concept_index.py")
    module.self_test()
