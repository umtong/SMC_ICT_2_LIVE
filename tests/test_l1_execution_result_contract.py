from __future__ import annotations

import json
from pathlib import Path


def test_l1_execution_result_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "research/reports/RES-20260725-1510-L1-EXEC-001.json").read_text())
    assert payload["status"] == "GOAL_NOT_MET_EXECUTION_LAYER_RETAINED"
    assert payload["champion_effect"] == "NONE"
    assert payload["decision"]["standalone_alpha"] == "REJECTED"
    rows = payload["selected_gate_cost_stress"]
    base = {row["split"]: row for row in rows if row["cost_multiplier"] == 1.0}
    assert set(base) == {"dev", "val", "conf"}
    assert all(base[split]["improvement_bps"] > 0 for split in base)
    assert all(base[split]["routed_mean_bps"] < 0 for split in base)
    assert base["dev"]["improvement_bps"] >= base["conf"]["improvement_bps"]
