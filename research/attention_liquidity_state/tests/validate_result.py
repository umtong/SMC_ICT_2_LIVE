from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    consolidated = json.loads((RESULTS / "consolidated_result.json").read_text())
    assert consolidated["status"] == "REJECTED_DEVELOPMENT_GATE"
    assert consolidated["goal_met"] is False
    counts = [
        consolidated["mechanisms"]["attention_liquidity_5m"]["total_configs"],
        consolidated["mechanisms"]["attention_breadth_switch"]["total_configs"],
        consolidated["mechanisms"]["state_first_hazard_direction"]["total_configs"],
        consolidated["mechanisms"]["cross_asset_smt"]["total_configs"],
        consolidated["mechanisms"]["native_bbo_absorption_reacceptance"]["config_count"],
    ]
    assert sum(counts) == 1536, counts
    gates = [
        consolidated["mechanisms"]["attention_liquidity_5m"]["development_gate_count"],
        consolidated["mechanisms"]["attention_breadth_switch"]["development_gates"],
        consolidated["mechanisms"]["state_first_hazard_direction"]["development_gates"],
        consolidated["mechanisms"]["cross_asset_smt"]["development_gates"],
        consolidated["mechanisms"]["native_bbo_absorption_reacceptance"]["development_gate_count"],
    ]
    assert sum(gates) == 0, gates

    md = pd.read_csv(RESULTS / "state_first_hazard_direction" / "model_diagnostics.csv")
    got_h = [float(md.hazard_auc.min()), float(md.hazard_auc.max())]
    got_d = [float(md.direction_auc_on_hazard.min()), float(md.direction_auc_on_hazard.max())]
    diag = consolidated["mechanisms"]["state_first_diagnostics"]
    assert max(abs(a - b) for a, b in zip(got_h, diag["hazard_auc_range"])) < 1e-12
    assert max(abs(a - b) for a, b in zip(got_d, diag["direction_auc_range"])) < 1e-12

    manifest = json.loads((RESULTS / "reusable_artifact_hashes.json").read_text())
    skip = {"README.md", "results/consolidated_result.json", "results/test_report.txt", "tests/validate_result.py"}
    for rel, expected in manifest.get("artifacts", {}).items():
        path = ROOT / rel
        if path.exists() and rel not in skip:
            assert sha256(path) == expected, rel
    print("VALIDATION OK: 1536 configs, 0 gates, diagnostics consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
