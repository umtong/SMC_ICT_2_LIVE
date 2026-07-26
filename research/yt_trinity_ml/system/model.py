from __future__ import annotations

from dataclasses import dataclass
from math import log

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression

from .core import EventCandidate


@dataclass(frozen=True)
class ModelConfig:
    learning_rate: float = 0.05
    max_leaf_nodes: int = 15
    max_iter: int = 250
    min_samples_leaf: int = 30
    l2_regularization: float = 1.0
    random_state: int = 20260727
    calibration_fraction: float = 0.20
    lower_confidence_penalty: float = 0.35


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: EventCandidate
    win_probability: float
    expected_net_r: float
    passive_fill_probability: float
    expected_log_growth: float
    lower_confidence_score: float


class ChronologicalEventModel:
    """Three-head event model with strictly later calibration data."""

    def __init__(self, config: ModelConfig = ModelConfig()) -> None:
        self.config = config
        self.feature_names: list[str] = []
        self.win_model = self._classifier()
        self.r_model = self._regressor()
        self.fill_model = self._classifier()
        self.calibrator = IsotonicRegression(out_of_bounds="clip")
        self._fitted = False

    def _classifier(self) -> HistGradientBoostingClassifier:
        return HistGradientBoostingClassifier(
            learning_rate=self.config.learning_rate,
            max_leaf_nodes=self.config.max_leaf_nodes,
            max_iter=self.config.max_iter,
            min_samples_leaf=self.config.min_samples_leaf,
            l2_regularization=self.config.l2_regularization,
            random_state=self.config.random_state,
        )

    def _regressor(self) -> HistGradientBoostingRegressor:
        return HistGradientBoostingRegressor(
            learning_rate=self.config.learning_rate,
            max_leaf_nodes=self.config.max_leaf_nodes,
            max_iter=self.config.max_iter,
            min_samples_leaf=self.config.min_samples_leaf,
            l2_regularization=self.config.l2_regularization,
            random_state=self.config.random_state,
            loss="squared_error",
        )

    def fit(self, rows: pd.DataFrame) -> "ChronologicalEventModel":
        required = {"event_start", "event_end", "target_before_stop", "net_r", "passive_filled"}
        missing = required - set(rows.columns)
        if missing:
            raise ValueError(f"training rows missing: {sorted(missing)}")
        ordered = rows.sort_values("event_end", kind="stable").reset_index(drop=True)
        if len(ordered) < max(50, self.config.min_samples_leaf * 2):
            raise ValueError("insufficient event rows")
        split = int(len(ordered) * (1 - self.config.calibration_fraction))
        split = min(max(split, 1), len(ordered) - 1)
        calibration = ordered.iloc[split:].copy()
        calibration_start = pd.to_datetime(calibration["event_start"], utc=True).min()
        base = ordered.iloc[:split].copy()
        base = base[pd.to_datetime(base["event_end"], utc=True) < calibration_start]
        if len(base) < max(25, self.config.min_samples_leaf):
            raise ValueError("insufficient purged base rows")
        leakage_columns = {"event_start", "event_end", "target_before_stop", "net_r", "passive_filled"}
        self.feature_names = [
            name
            for name in ordered.columns
            if name not in leakage_columns and pd.api.types.is_numeric_dtype(ordered[name])
        ]
        if not self.feature_names:
            raise ValueError("no numeric feature columns")
        x_base = base[self.feature_names].replace([np.inf, -np.inf], np.nan)
        self.win_model.fit(x_base, base["target_before_stop"].astype(int))
        self.r_model.fit(x_base, base["net_r"].astype(float))
        self.fill_model.fit(x_base, base["passive_filled"].astype(int))
        raw_calibration = self._positive_probability(
            self.win_model, calibration[self.feature_names].replace([np.inf, -np.inf], np.nan)
        )
        self.calibrator.fit(raw_calibration, calibration["target_before_stop"].astype(int).to_numpy())
        self._fitted = True
        return self

    @staticmethod
    def _positive_probability(model: HistGradientBoostingClassifier, values: pd.DataFrame) -> np.ndarray:
        probabilities = model.predict_proba(values)
        classes = np.asarray(model.classes_)
        positive = np.flatnonzero(classes == 1)
        if positive.size:
            return probabilities[:, int(positive[0])]
        return np.zeros(len(values), dtype=float)

    def score(
        self,
        candidate: EventCandidate,
        risk_fraction: float,
        winner_net_r: float,
        loser_net_r: float,
        fixed_cost_fraction: float,
    ) -> ScoredCandidate:
        if not self._fitted:
            raise RuntimeError("model not fitted")
        vector = pd.DataFrame(
            [{name: candidate.feature_row.get(name, np.nan) for name in self.feature_names}]
        ).replace([np.inf, -np.inf], np.nan)
        raw_p = float(self._positive_probability(self.win_model, vector)[0])
        p = float(self.calibrator.predict([raw_p])[0])
        expected_r = float(self.r_model.predict(vector)[0])
        fill = float(self._positive_probability(self.fill_model, vector)[0])
        win_return = risk_fraction * winner_net_r - fixed_cost_fraction
        loss_return = risk_fraction * loser_net_r - fixed_cost_fraction
        if win_return <= -1 or loss_return <= -1:
            expected_log = -np.inf
        else:
            expected_log = p * log(1 + win_return) + (1 - p) * log(1 + loss_return)
        disagreement = abs(expected_r - (p * winner_net_r + (1 - p) * loser_net_r))
        uncertainty = p * (1 - p)
        lower = expected_log - self.config.lower_confidence_penalty * (uncertainty + disagreement) * risk_fraction
        return ScoredCandidate(candidate, p, expected_r, fill, expected_log, lower)
