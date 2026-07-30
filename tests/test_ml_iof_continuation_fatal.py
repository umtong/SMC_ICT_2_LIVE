from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research" / "ml_iof_continuation_fatal"


def test_materialized_runner_and_result_contract() -> None:
    subprocess.run([sys.executable, str(RESEARCH / "materialize.py")], check=True)
    runner = RESEARCH / "run_fatal_screen.py"
    assert runner.is_file()
    result = json.loads((RESEARCH / "RESULT.json").read_text(encoding="utf-8"))
    assert result["status"] == "RETIRED_DETERMINISTIC_SUBCOST_AND_NEGATIVE_FIRST_PULLBACK"
    assert result["candidate_count"] == 1940
    assert result["official_2024_2026_opened"] is False
    assert result["orders_submitted"] is False
    cells = {(int(row["year"]), int(row["cost_bps"])): row for row in result["grid"]}
    assert cells[(2022, 24)]["multiple"] < 1.0
    assert cells[(2023, 24)]["multiple"] < 1.0
    assert cells[(2022, 12)]["multiple"] < 1.0
    assert cells[(2023, 12)]["multiple"] < 1.0
    assert cells[(2022, 24)]["winner_removed_multiple"] < 1.0
    assert cells[(2023, 24)]["winner_removed_multiple"] < 1.0


def test_contract_has_no_elapsed_time_exit_or_risk_rescue() -> None:
    contract = json.loads((RESEARCH / "CONTRACT.json").read_text(encoding="utf-8"))
    assert contract["risk_and_exit"]["elapsed_time_exit"] is False
    assert contract["risk_and_exit"]["stage_boundary_exit"] is False
    assert contract["account"]["risk_fraction"] == 0.005
    assert contract["account"]["notional_cap"] == 3.0
    assert contract["official_2024_2026_opened"] is False
    assert contract["orders_submitted"] is False
