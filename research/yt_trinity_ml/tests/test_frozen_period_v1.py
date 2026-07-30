from __future__ import annotations

import numpy as np
import pandas as pd

from run_frozen_period_v1 import (
    FrozenActionModel,
    FrozenQualityGate,
    _budget_targets,
    _candidate_features,
    _quality_eligible,
    _score_candidates,
)
from system.core import EventCandidate, EventFamily


class _FixedRegressor:
    def __init__(self, value: float) -> None:
        self.value = value

    def predict(self, values: pd.DataFrame) -> np.ndarray:
        return np.full(len(values), self.value, dtype=float)


def _candidate(
    family: EventFamily,
    feature_row: dict[str, float],
    *,
    entry: float = 100.0,
    stop: float = 96.0,
    target: float = 106.0,
) -> EventCandidate:
    return EventCandidate(
        timestamp=pd.Timestamp("2023-12-01T12:00:00Z"),
        symbol="BTCUSDT",
        family=family,
        side=1,
        decision_price=entry,
        entry_reference=entry,
        stop_reference=stop,
        target_reference=target,
        structural_level=99.0,
        feature_row=feature_row,
    )


def test_budget_targets_use_planned_loss_not_stop_distance_only() -> None:
    rows = pd.DataFrame(
        {
            "stop_distance_fraction": [0.01],
            "side": [1],
            "market_net_r": [2.0],
            "passive_net_r": [2.0],
        }
    )
    result = _budget_targets(rows)
    assert 0 < result.loc[0, "market_budget_r"] < 2.0
    assert result.loc[0, "passive_budget_r"] > result.loc[0, "market_budget_r"]


def test_family_specific_quality_gate_preserves_smc_geometry() -> None:
    gate = FrozenQualityGate()
    reversal = _candidate(
        EventFamily.LIQUIDITY_SWEEP_REVERSAL,
        {
            "target_distance_atr": 5.5,
            "sweep_depth_atr": 1.2,
            "stop_distance_atr": 4.0,
            "path_excursion_atr": 6.0,
        },
        target=105.0,
    )
    weak_reversal = _candidate(
        EventFamily.LIQUIDITY_SWEEP_REVERSAL,
        {"target_distance_atr": 5.4, "sweep_depth_atr": 1.2},
        target=105.0,
    )
    continuation = _candidate(
        EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION,
        {"stop_distance_atr": 4.0, "path_excursion_atr": 6.0},
        target=105.0,
    )
    weak_continuation = _candidate(
        EventFamily.DISPLACEMENT_BREAK_RETEST_CONTINUATION,
        {"stop_distance_atr": 3.9, "path_excursion_atr": 6.0},
        target=105.0,
    )
    assert _quality_eligible(reversal, gate)
    assert not _quality_eligible(weak_reversal, gate)
    assert _quality_eligible(continuation, gate)
    assert not _quality_eligible(weak_continuation, gate)


def test_cost_aware_ml_threshold_and_action_are_frozen() -> None:
    candidate = _candidate(
        EventFamily.LIQUIDITY_SWEEP_REVERSAL,
        {"target_distance_atr": 6.0, "sweep_depth_atr": 1.5},
        target=108.0,
    )
    scored, rows, counts = _score_candidates(
        [candidate],
        _FixedRegressor(-0.10),
        _FixedRegressor(0.25),
        FrozenActionModel(threshold_budget_r=-0.20),
    )
    assert len(scored) == 1
    assert scored[0].preferred_action == "PASSIVE_RETEST"
    assert scored[0].passive_lower_confidence_score == 0.45
    assert rows[0]["passes_threshold"] is True
    assert counts == {"PASSIVE_RETEST": 1}
    features = _candidate_features(candidate)
    assert features["symbol_btc"] == 1.0
    assert features["family_liquidity_sweep"] == 1.0
