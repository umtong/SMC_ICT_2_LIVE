from __future__ import annotations

import numpy as np
import pandas as pd

from system.core import EventCandidate, EventFamily
from system.model import ChronologicalEventModel, ModelConfig


class _FixedClassifier:
    classes_ = np.asarray([0, 1])

    def __init__(self, probability: float) -> None:
        self.probability = probability

    def predict_proba(self, values: pd.DataFrame) -> np.ndarray:
        probability = np.full(len(values), self.probability, dtype=float)
        return np.column_stack([1.0 - probability, probability])


class _IdentityCalibrator:
    def predict(self, values: list[float] | np.ndarray) -> np.ndarray:
        return np.asarray(values, dtype=float)


class _FixedRegressor:
    def __init__(self, value: float) -> None:
        self.value = value

    def predict(self, values: pd.DataFrame) -> np.ndarray:
        return np.full(len(values), self.value, dtype=float)


class _ColumnRegressor:
    def __init__(self, column: str) -> None:
        self.column = column

    def predict(self, values: pd.DataFrame) -> np.ndarray:
        return values[self.column].to_numpy(dtype=float)


def _candidate(reward_risk: float) -> EventCandidate:
    return EventCandidate(
        timestamp=pd.Timestamp("2023-01-01T00:00:00Z"),
        symbol="BTCUSDT",
        family=EventFamily.LIQUIDITY_SWEEP_REVERSAL,
        side=1,
        decision_price=100.0,
        entry_reference=100.0,
        stop_reference=99.0,
        target_reference=100.0 + reward_risk,
        structural_level=99.5,
        feature_row={},
    )


def test_candidate_specific_payoff_magnitude_changes_action_value() -> None:
    model = ChronologicalEventModel(ModelConfig(lower_confidence_penalty=0.0))
    model.feature_names = ["raw_reward_risk"]
    model.win_model = _FixedClassifier(0.55)
    model.calibrator = _IdentityCalibrator()
    model.r_model = _FixedRegressor(0.0)
    model.fill_model = _FixedClassifier(0.0)
    model.fill_calibrator = _IdentityCalibrator()
    model.market_win_r_model = _ColumnRegressor("raw_reward_risk")
    model.market_loss_r_model = _FixedRegressor(-1.0)
    model._market_win_r_fitted = True
    model._market_loss_r_fitted = True
    model._market_win_bounds = (0.01, 10.0)
    model._market_loss_bounds = (-2.0, -0.01)
    model._fitted = True

    low = model.score(
        _candidate(1.0),
        risk_fraction=0.01,
        winner_net_r=1.0,
        loser_net_r=-1.0,
        fixed_cost_fraction=0.0,
    )
    high = model.score(
        _candidate(4.0),
        risk_fraction=0.01,
        winner_net_r=1.0,
        loser_net_r=-1.0,
        fixed_cost_fraction=0.0,
    )

    assert high.win_probability == low.win_probability
    assert high.market_winner_net_r == 4.0
    assert low.market_winner_net_r == 1.0
    assert high.expected_net_r > low.expected_net_r
    assert high.market_expected_log_growth > low.market_expected_log_growth
    assert high.lower_confidence_score > low.lower_confidence_score


def test_unfitted_conditional_heads_preserve_distribution_fallback() -> None:
    model = ChronologicalEventModel(ModelConfig(lower_confidence_penalty=0.0))
    model.feature_names = ["raw_reward_risk"]
    model.win_model = _FixedClassifier(0.60)
    model.calibrator = _IdentityCalibrator()
    model.r_model = _FixedRegressor(0.5)
    model.fill_model = _FixedClassifier(0.0)
    model.fill_calibrator = _IdentityCalibrator()
    model._fitted = True

    scored = model.score(
        _candidate(5.0),
        risk_fraction=0.01,
        winner_net_r=1.75,
        loser_net_r=-0.90,
        fixed_cost_fraction=0.0,
    )

    assert scored.market_winner_net_r == 1.75
    assert scored.market_loser_net_r == -0.90
    assert np.isclose(scored.expected_net_r, 0.60 * 1.75 + 0.40 * -0.90)
