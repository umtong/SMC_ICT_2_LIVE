from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import apply_profit_first_patch as p


def test_frozen_source_patch_compiles_and_changes_only_declared_contract(
    tmp_path: Path,
) -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "ml_uniswap_hedge_transfer_economic_20260726"
        / "run.py"
    )
    output = tmp_path / "run_profit_first.py"
    p.patch(source, output)
    text = output.read_text()
    assert "PARTITION_BOUNDARY_STRUCTURAL_STOP" not in text
    assert "PARTITION_BOUNDARY_MARK" in text
    assert "positive_18bps" in text
    assert "growth_above_donchian_benchmark_24bps" not in text
    spec = importlib.util.spec_from_file_location("run_profit_first_test", output)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.self_test()
