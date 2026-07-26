from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_launcher():
    path = ROOT / "source_gate_launcher.py"
    spec = importlib.util.spec_from_file_location("source_gate_launcher", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_typo_is_unique_and_corrected_source_compiles() -> None:
    module = load_launcher()
    original = module.SOURCE.read_text(encoding="utf-8")
    assert original.count(module.BAD) == 1
    corrected = module.corrected_source_text()
    assert module.BAD not in corrected
    assert corrected.count(module.GOOD) >= 1
    compile(corrected, str(module.SOURCE), "exec")


def test_replacement_changes_only_the_unique_frozen_sequence() -> None:
    module = load_launcher()
    original = module.SOURCE.read_text(encoding="utf-8")
    corrected = module.corrected_source_text()
    assert corrected == original.replace(module.BAD, module.GOOD)
