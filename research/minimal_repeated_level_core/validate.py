from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_runner():
    spec = importlib.util.spec_from_file_location("minimal_repeated_level_runner", ROOT / "run.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    runner = load_runner()
    runner.test_semantics()
    result = json.loads((ROOT / "RESULT.json").read_text())
    contract = json.loads((ROOT / "CONTRACT.json").read_text())
    attestation = json.loads((ROOT / "VALIDATION_ATTESTATION.json").read_text())
    manifest = json.loads((ROOT / "EVIDENCE_MANIFEST.json").read_text())
    assert result["result_id"] == contract["result_id"] == attestation["result_id"] == manifest["result_id"]
    assert result["status"] == "RETIRED_PRE2024_SPARSE_MODEL_ONLY_EDGE_NOT_CORE"
    assert result["opened_2023"] is False and result["opened_official_2024_2026"] is False
    assert result["gate"]["passed"] is False and result["gate"]["at_least_100_completed_trades"] is False
    assert result["model_account_2022"]["24"]["completed_trade_count"] == 32
    assert abs(result["model_account_2022"]["24"]["final_multiple"] - 1.0150020141676572) < 1e-12
    assert result["deterministic_2022_24bp"]["BREAK"]["final_multiple"] < 1.0
    assert result["deterministic_2022_24bp"]["REJECT"]["final_multiple"] < 1.0
    assert result["winner_removal_24bp"]["metrics"]["final_multiple"] < 1.001
    assert result["lower_tail_24bp"]["monthly_q05_multiple"] < 1.0
    assert result["lower_tail_24bp"]["event_q05_multiple"] < 1.0
    print(json.dumps({"validated": True, "result_id": result["result_id"], "status": result["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
