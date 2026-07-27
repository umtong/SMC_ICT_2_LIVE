from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.pipeline import make_pipeline


@dataclass(frozen=True)
class GroupedActionModelConfig:
    learning_rate: float = 0.04
    max_leaf_nodes: int = 15
    min_samples_leaf: int = 35
    max_iter: int = 320
    l2_regularization: float = 3.0
    calibration_fraction: float = 0.20
    lower_confidence_penalty: float = 0.35
    minimum_group_rows: int = 100
    random_state: int = 20260727


@dataclass
class _ActionHead:
    classifier: Any
    mean_regressor: Any
    win_regressor: Any | None
    loss_regressor: Any | None
    calibrator: IsotonicRegression | None
    fallback_win_r: float
    fallback_loss_r: float
    residual_scale: float
    training_rows: int
    base_rows: int
    calibration_rows: int


class GroupedCausalActionValueModel:
    """Causal action-specific model for already valid SMC/ICT narratives.

    The model never creates a setup. It ranks a causally armed passive action or a
    later confirmed market action. Each action has separate probability and payoff
    heads so nonfills and market outcomes cannot be averaged into one shortcut.
    """

    def __init__(self, config: GroupedActionModelConfig = GroupedActionModelConfig()) -> None:
        self.config = config
        self.feature_names: list[str] = []
        self.heads: dict[str, _ActionHead] = {}
        self.pooled_head: _ActionHead | None = None
        self.fitted = False

    def _classifier(self):
        return make_pipeline(
            SimpleImputer(strategy="median"),
            HistGradientBoostingClassifier(
                learning_rate=self.config.learning_rate,
                max_leaf_nodes=self.config.max_leaf_nodes,
                min_samples_leaf=self.config.min_samples_leaf,
                max_iter=self.config.max_iter,
                l2_regularization=self.config.l2_regularization,
                random_state=self.config.random_state,
            ),
        )

    def _regressor(self):
        return make_pipeline(
            SimpleImputer(strategy="median"),
            HistGradientBoostingRegressor(
                learning_rate=self.config.learning_rate,
                max_leaf_nodes=self.config.max_leaf_nodes,
                min_samples_leaf=self.config.min_samples_leaf,
                max_iter=self.config.max_iter,
                l2_regularization=self.config.l2_regularization,
                random_state=self.config.random_state,
                loss="squared_error",
            ),
        )

    @staticmethod
    def _probability(model: Any, values: pd.DataFrame) -> np.ndarray:
        classifier = model[-1]
        probabilities = model.predict_proba(values)
        classes = np.asarray(classifier.classes_)
        positive = np.flatnonzero(classes == 1)
        return probabilities[:, int(positive[0])] if positive.size else np.zeros(len(values))

    def _fit_head(self, rows: pd.DataFrame) -> _ActionHead | None:
        ordered = rows.sort_values(["event_end", "activation"], kind="stable").reset_index(drop=True)
        if len(ordered) < self.config.minimum_group_rows:
            return None
        split = int(len(ordered) * (1.0 - self.config.calibration_fraction))
        split = min(max(split, 1), len(ordered) - 1)
        calibration = ordered.iloc[split:].copy()
        calibration_start = pd.to_datetime(calibration["activation"], utc=True).min()
        base = ordered.iloc[:split].copy()
        base = base[pd.to_datetime(base["event_end"], utc=True) < calibration_start]
        minimum_base = max(50, self.config.min_samples_leaf * 2)
        if len(base) < minimum_base:
            return None

        x_base = base[self.feature_names].replace([np.inf, -np.inf], np.nan)
        y_positive = base["net_budget_r"].astype(float).gt(0).astype(int)
        if y_positive.nunique() < 2:
            return None
        classifier = self._classifier()
        classifier.fit(x_base, y_positive)
        mean_regressor = self._regressor()
        mean_regressor.fit(x_base, base["net_budget_r"].astype(float))

        wins = base[base["net_budget_r"].astype(float) > 0]
        losses = base[base["net_budget_r"].astype(float) <= 0]
        fallback_win = float(wins["net_budget_r"].median()) if len(wins) else 1.0
        fallback_loss = float(losses["net_budget_r"].median()) if len(losses) else -1.0
        win_regressor = None
        loss_regressor = None
        minimum_conditional = max(30, self.config.min_samples_leaf)
        if len(wins) >= minimum_conditional:
            win_regressor = self._regressor()
            win_regressor.fit(
                wins[self.feature_names].replace([np.inf, -np.inf], np.nan),
                wins["net_budget_r"].astype(float),
            )
        if len(losses) >= minimum_conditional:
            loss_regressor = self._regressor()
            loss_regressor.fit(
                losses[self.feature_names].replace([np.inf, -np.inf], np.nan),
                losses["net_budget_r"].astype(float),
            )

        calibrator = None
        residual_scale = float(np.median(np.abs(base["net_budget_r"] - base["net_budget_r"].median())))
        if len(calibration) >= 10:
            x_cal = calibration[self.feature_names].replace([np.inf, -np.inf], np.nan)
            raw = self._probability(classifier, x_cal)
            targets = calibration["net_budget_r"].astype(float).gt(0).astype(int).to_numpy()
            if np.unique(targets).size >= 2 and np.unique(raw).size >= 2:
                calibrator = IsotonicRegression(out_of_bounds="clip")
                calibrator.fit(raw, targets)
            mean_prediction = mean_regressor.predict(x_cal)
            residual_scale = max(
                residual_scale,
                float(np.quantile(np.abs(calibration["net_budget_r"].to_numpy(float) - mean_prediction), 0.70)),
            )
        return _ActionHead(
            classifier=classifier,
            mean_regressor=mean_regressor,
            win_regressor=win_regressor,
            loss_regressor=loss_regressor,
            calibrator=calibrator,
            fallback_win_r=max(fallback_win, 0.001),
            fallback_loss_r=min(fallback_loss, -0.001),
            residual_scale=max(residual_scale, 0.05),
            training_rows=len(ordered),
            base_rows=len(base),
            calibration_rows=len(calibration),
        )

    def fit(self, rows: pd.DataFrame, feature_names: Sequence[str]) -> "GroupedCausalActionValueModel":
        required = {"activation", "event_end", "action", "net_budget_r"}
        missing = required - set(rows.columns)
        if missing:
            raise ValueError(f"action-value rows missing: {sorted(missing)}")
        self.feature_names = list(feature_names)
        if not self.feature_names:
            raise ValueError("no causal numeric action features")
        self.pooled_head = self._fit_head(rows)
        for action, group in rows.groupby("action", sort=True):
            head = self._fit_head(group)
            if head is not None:
                self.heads[str(action)] = head
        if self.pooled_head is None and not self.heads:
            raise ValueError("insufficient causal action rows")
        self.fitted = True
        return self

    def _predict_head(self, head: _ActionHead, rows: pd.DataFrame) -> pd.DataFrame:
        values = rows[self.feature_names].replace([np.inf, -np.inf], np.nan)
        raw_probability = self._probability(head.classifier, values)
        probability = (
            head.calibrator.predict(raw_probability)
            if head.calibrator is not None
            else raw_probability
        )
        mean_r = head.mean_regressor.predict(values)
        if head.win_regressor is not None:
            winner_r = np.maximum(head.win_regressor.predict(values), 0.001)
        else:
            winner_r = np.full(len(values), head.fallback_win_r)
        if head.loss_regressor is not None:
            loser_r = np.minimum(head.loss_regressor.predict(values), -0.001)
        else:
            loser_r = np.full(len(values), head.fallback_loss_r)
        expected_r = probability * winner_r + (1.0 - probability) * loser_r
        disagreement = np.abs(expected_r - mean_r)
        uncertainty = probability * (1.0 - probability)
        lower = expected_r - self.config.lower_confidence_penalty * (
            disagreement + uncertainty * head.residual_scale
        )
        return pd.DataFrame(
            {
                "win_probability": probability,
                "winner_net_r": winner_r,
                "loser_net_r": loser_r,
                "unconditional_net_r": mean_r,
                "expected_net_r": expected_r,
                "lower_confidence_net_r": lower,
            },
            index=rows.index,
        )

    def predict(self, rows: pd.DataFrame) -> pd.DataFrame:
        if not self.fitted:
            raise RuntimeError("grouped action model is not fitted")
        result = pd.DataFrame(index=rows.index)
        chunks: list[pd.DataFrame] = []
        for action, group in rows.groupby("action", sort=False):
            head = self.heads.get(str(action)) or self.pooled_head
            if head is None:
                continue
            scored = self._predict_head(head, group)
            scored["action"] = str(action)
            chunks.append(scored)
        if not chunks:
            return result
        return pd.concat(chunks).sort_index()

    def diagnostics(self) -> dict[str, Any]:
        def payload(head: _ActionHead | None) -> dict[str, Any] | None:
            if head is None:
                return None
            return {
                "training_rows": head.training_rows,
                "base_rows": head.base_rows,
                "calibration_rows": head.calibration_rows,
                "fallback_win_r": head.fallback_win_r,
                "fallback_loss_r": head.fallback_loss_r,
                "residual_scale": head.residual_scale,
                "win_regressor_fitted": head.win_regressor is not None,
                "loss_regressor_fitted": head.loss_regressor is not None,
                "probability_calibrated": head.calibrator is not None,
            }
        return {
            "config": self.config.__dict__,
            "feature_count": len(self.feature_names),
            "actions": {name: payload(head) for name, head in sorted(self.heads.items())},
            "pooled": payload(self.pooled_head),
        }

    def fingerprint(self) -> str:
        payload = {
            "config": self.config.__dict__,
            "feature_names": self.feature_names,
            "diagnostics": self.diagnostics(),
        }
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
