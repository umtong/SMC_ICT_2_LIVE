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
class HistoryActionModelConfig:
    learning_rate: float = 0.04
    max_leaf_nodes: int = 15
    min_samples_leaf: int = 35
    max_iter: int = 320
    l2_regularization: float = 3.0
    lower_confidence_penalty: float = 0.35
    minimum_base_rows: int = 100
    minimum_outcome_rows: int = 50
    random_state: int = 20260727


@dataclass
class _Head:
    action: str
    passive: bool
    fill_classifier: Any | None
    fill_calibrator: IsotonicRegression | None
    positive_classifier: Any
    positive_calibrator: IsotonicRegression | None
    unconditional_regressor: Any
    winner_regressor: Any | None
    loser_regressor: Any | None
    fallback_fill_probability: float
    fallback_winner_r: float
    fallback_loser_r: float
    residual_scale: float
    base_rows: int
    calibration_rows: int
    outcome_base_rows: int
    outcome_calibration_rows: int


class ExplicitHistoryActionValueModel:
    """Action-specific SMC value model with explicit date-partitioned calibration.

    The caller supplies base and calibration rows separately. This class never chooses
    those periods by row count, so sparse regimes cannot move a calibration boundary.
    Passive nonfill remains zero return and is modeled separately from conditional
    filled-trade outcomes.
    """

    def __init__(self, config: HistoryActionModelConfig = HistoryActionModelConfig()) -> None:
        self.config = config
        self.feature_names: list[str] = []
        self.heads: dict[str, _Head] = {}
        self.base_rows_digest: str | None = None
        self.calibration_rows_digest: str | None = None
        self.fitted = False

    @staticmethod
    def _rows_digest(rows: pd.DataFrame, feature_names: Sequence[str]) -> str:
        """Hash the exact causal feature/label multiset used by a fitted model."""
        identity = (
            "activation", "event_end", "symbol", "action", "exit_variant",
            "filled", "net_budget_r",
        )
        columns = [name for name in identity if name in rows.columns]
        columns.extend(name for name in feature_names if name in rows.columns and name not in columns)
        frame = rows[columns].copy()
        for name in ("activation", "event_end"):
            if name in frame.columns:
                frame[name] = pd.to_datetime(frame[name], utc=True).astype("int64")
        row_hashes = pd.util.hash_pandas_object(
            frame, index=False, categorize=True
        ).to_numpy(dtype=np.uint64)
        row_hashes.sort()
        metadata = {
            "columns": columns,
            "dtypes": [str(frame[name].dtype) for name in columns],
            "rows": int(len(frame)),
        }
        digest = sha256(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(row_hashes.tobytes())
        return digest.hexdigest()

    def _classifier(self) -> Any:
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

    def _regressor(self) -> Any:
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
    def _positive_probability(model: Any, values: pd.DataFrame) -> np.ndarray:
        probabilities = model.predict_proba(values)
        classes = np.asarray(model[-1].classes_)
        positive = np.flatnonzero(classes == 1)
        return probabilities[:, int(positive[0])] if positive.size else np.zeros(len(values))

    @staticmethod
    def _calibrator(raw: np.ndarray, truth: np.ndarray) -> IsotonicRegression | None:
        if len(raw) < 10 or np.unique(raw).size < 2 or np.unique(truth).size < 2:
            return None
        model = IsotonicRegression(out_of_bounds="clip")
        model.fit(raw, truth)
        return model

    def _fit_head(
        self,
        action: str,
        base: pd.DataFrame,
        calibration: pd.DataFrame,
    ) -> _Head | None:
        if len(base) < self.config.minimum_base_rows:
            return None
        passive = "PASSIVE" in action.upper()
        x_base_all = base[self.feature_names].replace([np.inf, -np.inf], np.nan)

        unconditional = self._regressor()
        unconditional.fit(x_base_all, base["net_budget_r"].astype(float))

        fill_classifier = None
        fill_calibrator = None
        fallback_fill = 1.0
        outcome_base = base
        outcome_calibration = calibration
        if passive:
            fallback_fill = float(base["filled"].astype(int).mean())
            fill_truth = base["filled"].astype(int)
            if fill_truth.nunique() >= 2:
                fill_classifier = self._classifier()
                fill_classifier.fit(x_base_all, fill_truth)
                if len(calibration):
                    x_fill_cal = calibration[self.feature_names].replace([np.inf, -np.inf], np.nan)
                    raw_fill = self._positive_probability(fill_classifier, x_fill_cal)
                    fill_calibrator = self._calibrator(
                        raw_fill,
                        calibration["filled"].astype(int).to_numpy(),
                    )
            outcome_base = base[base["filled"].astype(int).eq(1)].copy()
            outcome_calibration = calibration[calibration["filled"].astype(int).eq(1)].copy()

        if len(outcome_base) < self.config.minimum_outcome_rows:
            return None
        x_outcome = outcome_base[self.feature_names].replace([np.inf, -np.inf], np.nan)
        positive_truth = outcome_base["net_budget_r"].astype(float).gt(0).astype(int)
        if positive_truth.nunique() < 2:
            return None
        positive_classifier = self._classifier()
        positive_classifier.fit(x_outcome, positive_truth)

        positive_calibrator = None
        if len(outcome_calibration):
            x_positive_cal = outcome_calibration[self.feature_names].replace([np.inf, -np.inf], np.nan)
            raw_positive = self._positive_probability(positive_classifier, x_positive_cal)
            positive_calibrator = self._calibrator(
                raw_positive,
                outcome_calibration["net_budget_r"].astype(float).gt(0).astype(int).to_numpy(),
            )

        wins = outcome_base[outcome_base["net_budget_r"].astype(float) > 0].copy()
        losses = outcome_base[outcome_base["net_budget_r"].astype(float) <= 0].copy()
        fallback_winner = float(wins["net_budget_r"].median()) if len(wins) else 1.0
        fallback_loser = float(losses["net_budget_r"].median()) if len(losses) else -1.0
        winner_regressor = None
        loser_regressor = None
        minimum_conditional = max(30, self.config.min_samples_leaf)
        if len(wins) >= minimum_conditional:
            winner_regressor = self._regressor()
            winner_regressor.fit(
                wins[self.feature_names].replace([np.inf, -np.inf], np.nan),
                wins["net_budget_r"].astype(float),
            )
        if len(losses) >= minimum_conditional:
            loser_regressor = self._regressor()
            loser_regressor.fit(
                losses[self.feature_names].replace([np.inf, -np.inf], np.nan),
                losses["net_budget_r"].astype(float),
            )

        residuals: list[float] = []
        if len(calibration):
            x_cal = calibration[self.feature_names].replace([np.inf, -np.inf], np.nan)
            predicted = unconditional.predict(x_cal)
            residuals.extend(
                np.abs(calibration["net_budget_r"].to_numpy(float) - predicted).tolist()
            )
        if residuals:
            residual_scale = float(np.quantile(np.asarray(residuals, dtype=float), 0.70))
        else:
            residual_scale = float(
                np.median(
                    np.abs(
                        base["net_budget_r"].to_numpy(float)
                        - float(base["net_budget_r"].median())
                    )
                )
            )

        return _Head(
            action=action,
            passive=passive,
            fill_classifier=fill_classifier,
            fill_calibrator=fill_calibrator,
            positive_classifier=positive_classifier,
            positive_calibrator=positive_calibrator,
            unconditional_regressor=unconditional,
            winner_regressor=winner_regressor,
            loser_regressor=loser_regressor,
            fallback_fill_probability=float(np.clip(fallback_fill, 0.0, 1.0)),
            fallback_winner_r=max(fallback_winner, 0.001),
            fallback_loser_r=min(fallback_loser, -0.001),
            residual_scale=max(residual_scale, 0.05),
            base_rows=len(base),
            calibration_rows=len(calibration),
            outcome_base_rows=len(outcome_base),
            outcome_calibration_rows=len(outcome_calibration),
        )

    def fit(
        self,
        base_rows: pd.DataFrame,
        calibration_rows: pd.DataFrame,
        feature_names: Sequence[str],
    ) -> "ExplicitHistoryActionValueModel":
        required = {"activation", "event_end", "action", "filled", "net_budget_r"}
        for name, rows in (("base", base_rows), ("calibration", calibration_rows)):
            missing = required - set(rows.columns)
            if missing:
                raise ValueError(f"{name} action rows missing: {sorted(missing)}")
        self.feature_names = list(feature_names)
        if not self.feature_names:
            raise ValueError("no causal action features")
        self.base_rows_digest = self._rows_digest(base_rows, self.feature_names)
        self.calibration_rows_digest = self._rows_digest(calibration_rows, self.feature_names)
        actions = sorted(set(base_rows["action"].astype(str)))
        for action in actions:
            base = base_rows[base_rows["action"].astype(str).eq(action)].copy()
            calibration = calibration_rows[
                calibration_rows["action"].astype(str).eq(action)
            ].copy()
            head = self._fit_head(action, base, calibration)
            if head is not None:
                self.heads[action] = head
        if not self.heads:
            raise ValueError("no action head met explicit-history sample requirements")
        self.fitted = True
        return self

    def _predict_head(self, head: _Head, rows: pd.DataFrame) -> pd.DataFrame:
        values = rows[self.feature_names].replace([np.inf, -np.inf], np.nan)
        if head.passive and head.fill_classifier is not None:
            raw_fill = self._positive_probability(head.fill_classifier, values)
            fill_probability = (
                head.fill_calibrator.predict(raw_fill)
                if head.fill_calibrator is not None
                else raw_fill
            )
        elif head.passive:
            fill_probability = np.full(len(rows), head.fallback_fill_probability)
        else:
            fill_probability = np.ones(len(rows))

        raw_positive = self._positive_probability(head.positive_classifier, values)
        positive_probability = (
            head.positive_calibrator.predict(raw_positive)
            if head.positive_calibrator is not None
            else raw_positive
        )
        unconditional = head.unconditional_regressor.predict(values)
        winner = (
            np.maximum(head.winner_regressor.predict(values), 0.001)
            if head.winner_regressor is not None
            else np.full(len(rows), head.fallback_winner_r)
        )
        loser = (
            np.minimum(head.loser_regressor.predict(values), -0.001)
            if head.loser_regressor is not None
            else np.full(len(rows), head.fallback_loser_r)
        )
        conditional = positive_probability * winner + (1.0 - positive_probability) * loser
        expected = fill_probability * conditional
        disagreement = np.abs(expected - unconditional)
        uncertainty = (
            fill_probability * positive_probability * (1.0 - positive_probability)
            + fill_probability * (1.0 - fill_probability)
        )
        lower = expected - self.config.lower_confidence_penalty * (
            disagreement + uncertainty * head.residual_scale
        )
        return pd.DataFrame(
            {
                "fill_probability": fill_probability,
                "win_probability_given_fill": positive_probability,
                "winner_net_r": winner,
                "loser_net_r": loser,
                "unconditional_net_r": unconditional,
                "conditional_expected_net_r": conditional,
                "expected_net_r": expected,
                "lower_confidence_net_r": lower,
            },
            index=rows.index,
        )

    def predict(self, rows: pd.DataFrame) -> pd.DataFrame:
        if not self.fitted:
            raise RuntimeError("explicit history model is not fitted")
        chunks: list[pd.DataFrame] = []
        for action, group in rows.groupby("action", sort=False):
            head = self.heads.get(str(action))
            if head is None:
                continue
            chunks.append(self._predict_head(head, group))
        if not chunks:
            return pd.DataFrame(index=rows.index)
        return pd.concat(chunks).sort_index()

    def diagnostics(self) -> dict[str, Any]:
        return {
            "config": self.config.__dict__,
            "feature_count": len(self.feature_names),
            "base_rows_digest": self.base_rows_digest,
            "calibration_rows_digest": self.calibration_rows_digest,
            "actions": {
                action: {
                    "passive": head.passive,
                    "base_rows": head.base_rows,
                    "calibration_rows": head.calibration_rows,
                    "outcome_base_rows": head.outcome_base_rows,
                    "outcome_calibration_rows": head.outcome_calibration_rows,
                    "fill_model_fitted": head.fill_classifier is not None,
                    "fill_calibrated": head.fill_calibrator is not None,
                    "positive_calibrated": head.positive_calibrator is not None,
                    "winner_regressor_fitted": head.winner_regressor is not None,
                    "loser_regressor_fitted": head.loser_regressor is not None,
                    "fallback_fill_probability": head.fallback_fill_probability,
                    "fallback_winner_r": head.fallback_winner_r,
                    "fallback_loser_r": head.fallback_loser_r,
                    "residual_scale": head.residual_scale,
                }
                for action, head in sorted(self.heads.items())
            },
        }

    def fingerprint(self) -> str:
        payload = {
            "config": self.config.__dict__,
            "feature_names": self.feature_names,
            "base_rows_digest": self.base_rows_digest,
            "calibration_rows_digest": self.calibration_rows_digest,
            "diagnostics": self.diagnostics(),
        }
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
