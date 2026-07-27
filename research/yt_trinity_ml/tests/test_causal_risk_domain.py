from __future__ import annotations

import pandas as pd

from run_causal_action_v1 import _causal_risk_grid


def test_risk_grid_reaches_data_implied_ruin_boundary_without_crossing_it() -> None:
    rows = pd.DataFrame({"net_budget_r": [-1.25, -0.8, 2.0, 0.0]})
    grid, info = _causal_risk_grid(rows)
    expected_boundary = 1.0 / 1.25
    assert info["single_trade_ruin_boundary"] == expected_boundary
    assert max(grid) <= 0.98 * expected_boundary + 1e-12
    assert max(grid) > 0.5
    assert 0.01 in grid


def test_heavier_loss_tail_reduces_risk_domain() -> None:
    mild, mild_info = _causal_risk_grid(pd.DataFrame({"net_budget_r": [-1.0, 1.0]}))
    heavy, heavy_info = _causal_risk_grid(pd.DataFrame({"net_budget_r": [-4.0, 1.0]}))
    assert max(heavy) < max(mild)
    assert heavy_info["single_trade_ruin_boundary"] == 0.25
