from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("run_screen.py")
SPEC = importlib.util.spec_from_file_location("run_screen", MODULE_PATH)
assert SPEC and SPEC.loader
run_screen = importlib.util.module_from_spec(SPEC)
sys.modules["run_screen"] = run_screen
SPEC.loader.exec_module(run_screen)


def test_frozen_candidate_count() -> None:
    grid = run_screen.candidate_grid()
    assert len(grid) == 108
    assert len({candidate.candidate_id for candidate in grid}) == 108


def test_self_tests() -> None:
    result = run_screen.run_self_tests()
    assert all(result.values())


def test_quarter_expiry_calendar() -> None:
    assert run_screen.last_friday(2023, 3).isoformat() == "2023-03-31T08:00:00+00:00"
    assert run_screen.last_friday(2023, 6).isoformat() == "2023-06-30T08:00:00+00:00"


def test_funding_cashflow_sign() -> None:
    import pandas as pd

    rates = pd.DataFrame(
        {
            "funding_time_ms": [10, 20],
            "funding_rate": [0.001, -0.0005],
            "mark_price": [100.0, 100.0],
        }
    )
    assert run_screen.funding_bps_between(rates, 0, 20, 1) == -5.0
    assert run_screen.funding_bps_between(rates, 0, 20, -1) == 5.0
