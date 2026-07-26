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


def test_source_compiles_with_preoutcome_corrections() -> None:
    module = load_launcher()
    original = module.SOURCE.read_text(encoding="utf-8")
    assert original.count(module.BAD) in {0, 1}
    assert original.count(module.FUTURE_BYBIT_PROBE) in {0, 1}
    corrected = module.corrected_source_text()
    assert module.BAD not in corrected
    assert corrected.count(module.GOOD) >= 1
    assert module.FUTURE_BYBIT_PROBE not in corrected
    assert corrected.count(module.PRE2024_BYBIT_PROBE) == 1
    compile(corrected, str(module.SOURCE), "exec")


def test_correction_is_idempotent() -> None:
    module = load_launcher()
    original = module.SOURCE.read_text(encoding="utf-8")
    expected = original.replace(module.BAD, module.GOOD)
    if module.FUTURE_BYBIT_PROBE in expected:
        expected = expected.replace(module.FUTURE_BYBIT_PROBE, module.PRE2024_BYBIT_PROBE)
    corrected = module.corrected_source_text()
    assert corrected == expected
