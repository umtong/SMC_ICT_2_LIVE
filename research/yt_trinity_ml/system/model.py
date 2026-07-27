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
    conditional_return_min_samples: int = 20
    return_clip_lower_quantile: float = 0.02
    return_clip_upper_quantile: float = 0.98


@dataclass(frozen=True)
class ScoredCandidate:
    # The first six fields preserve the original public API. The action-specific
    # fields remove the invalid shortcut of using a market-order label to choose a
    # passive order.
    candidate: EventCandidate
    win_probability: float
    expected_net_r: float
    passive_fill_probability: float
    expected_log_growth: float
    lower_confidence_score: float
    passive_win_probability: float | None = None
    market_expected_log_growth: float | None = None
    passive_expected_log_growth: float | None = None
    market_lower_confidence_score: float | None = None
    passive_lower_confidence_score: float | None = None
    preferred_action: str | None = None
    market_winner_net_r: float | None = None
    market_loser_net_r: float | None = None
    passive_winner_net_r: float | None = None
    passive_loser_net_r: float | None = None
    passive_conditional_expected_net_r: float | None = None
    market_unconditional_expected_net_r: float | None = None
    passive_unconditional_expected_net_r: float | None = None


def candidate_model_features(candidate: EventCandidate) -> dict[str, float]:
    """Return the exact numeric feature vector used for both fitting and scoring."""
    row = {
        str(key): float(value)
        for key, value in candidate.feature_row.items()
        if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value)
    }
    row.update(
        {
            "side": float(candidate.side),
            "stop_distance_fraction": candidate.stop_distance / max(candidate.entry_reference, 1e-12),
            "target_distance_fraction": candidate.target_distance / max(candidate.entry_reference, 1e-12),
            "raw_reward_risk": candidate.target_distance / max(candidate.stop_distance, 1e-12),
            "family_liquidity_sweep": float(candidate.family.value == "LIQUIDITY_SWEEP_REVERSAL"),
            "family_displacement_retest": float(
                candidate.family.value == "DISPLACEMENT_BREAK_RETEST_CONTINUATION"
            ),
            "symbol_btc": float(candidate.symbol == "BTCUSDT"),
            "symbol_eth": float(candidate.symbol == "ETHUSDT"),
            "symbol_sol": float(candidate.symbol == "SOLUSDT"),
            "symbol_xrp": float(candidate.symbol == "XRPUSDT"),
        }
    )
    return row


class ChronologicalEventModel:
    """Causal action-value model with strictly later calibration data.

    MARKETABLE and PASSIVE_RETEST are different actions. The market head predicts
    the after-cost first-passage result of an immediately executable entry. The
    passive heads predict fill probability and conditional after-cost outcome; a
    nonfill contributes zero account return rather than inheriting the market label.

    Win probability alone is not action value. Two candidates with the same win
    probability but different structural reward-to-risk must not receive the same
    expected growth. Conditional winner and loser return heads therefore estimate
    the candidate-specific after-cost payoff magnitudes used by the log-growth
    objective. An unconditional return head remains as an independent disagreement
    check rather than replacing those payoff estimates with a global median.
    """

    def __init__(self, config: ModelConfig = ModelConfig()) -> None:
        self.config = config
        self.feature_names: list[str] = []
        self.win_model = self._classifier()
        self.r_model = self._regressor()
        self.fill_model = self._classifier()
        self.passive_win_model = self._classifier()
        self.passive_r_model = self._regressor()
        self.market_win_r_model = self._regressor()
        self.market_loss_r_model = self._regressor()
        self.passive_win_r_model = self._regressor()
        self.passive_loss_r_model = self._regressor()
        self.calibrator = IsotonicRegression(out_of_bounds="clip")
        self.fill_calibrator = IsotonicRegression(out_of_bounds="clip")
        self.passive_calibrator = IsotonicRegression(out_of_bounds="clip")
        self._fill_calibrator_fitted = False
        self._market_win_r_fitted = False
        self._market_loss_r_fitted = False
        self._passive_win_r_fitted = False
        self._passive_loss_r_fitted = False
        self._market_win_bounds = (0.01, np.inf)
        self._market_loss_bounds = (-np.inf, -0.01)
        self._passive_win_bounds = (0.01, np.inf)
        self._passive_loss_bounds = (-np.inf, -0.01)
        self._passive_outcome_fitted = False
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

    @staticmethod
    def _with_action_labels(rows: pd.DataFrame) -> pd.DataFrame:
        result = rows.copy()
        if "market_target_before_stop" not in result.columns and "target_before_stop" in result.columns:
            result["market_target_before_stop"] = result["target_before_stop"]
        if "market_net_r" not in result.columns and "net_r" in result.columns:
            result["market_net_r"] = result["net_r"]
        if "passive_target_before_stop" not in result.columns:
            result["passive_target_before_stop"] = np.where(
                pd.to_numeric(result.get("passive_filled", 0), errors="coerce").fillna(0).astype(int).eq(1),
                result.get("market_target_before_stop"),
                np.nan,
            )
        if "passive_net_r" not in result.columns:
            result["passive_net_r"] = np.where(
                pd.to_numeric(result.get("passive_filled", 0), errors="coerce").fillna(0).astype(int).eq(1),
                result.get("market_net_r"),
                0.0,
            )
        if "market_budget_r" in result.columns:
            result["market_net_r"] = result["market_budget_r"]
        if "passive_budget_r" in result.columns:
            result["passive_net_r"] = result["passive_budget_r"]
        return result

    def _return_bounds(self, values: pd.Series, winner: bool) -> tuple[float, float]:
        clean = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if clean.empty:
            return (0.01, np.inf) if winner else (-np.inf, -0.01)
        lower_q = min(max(float(self.config.return_clip_lower_quantile), 0.0), 1.0)
        upper_q = min(max(float(self.config.return_clip_upper_quantile), lower_q), 1.0)
        lower = float(clean.quantile(lower_q))
        upper = float(clean.quantile(upper_q))
        if winner:
            lower = max(0.001, lower)
            upper = max(lower, upper)
        else:
            upper = min(-0.001, upper)
            lower = min(lower, upper)
        return lower, upper

    def _fit_return_head(
        self,
        model: HistGradientBoostingRegressor,
        rows: pd.DataFrame,
        return_column: str,
    ) -> tuple[bool, tuple[float, float]]:
        minimum = max(2, int(self.config.conditional_return_min_samples), int(self.config.min_samples_leaf))
        usable = rows[rows[return_column].notna()]
        if len(usable) < minimum:
            return False, (-np.inf, np.inf)
        x_values = usable[self.feature_names].replace([np.inf, -np.inf], np.nan)
        model.fit(x_values, usable[return_column].astype(float))
        winner = bool((usable[return_column].astype(float) > 0).mean() >= 0.5)
        return True, self._return_bounds(usable[return_column], winner)

    def fit(self, rows: pd.DataFrame) -> "ChronologicalEventModel":
        required = {"event_start", "event_end", "passive_filled"}
        missing = required - set(rows.columns)
        if missing:
            raise ValueError(f"training rows missing: {sorted(missing)}")
        ordered = self._with_action_labels(rows).sort_values("event_end", kind="stable").reset_index(drop=True)
        action_required = {"market_target_before_stop", "market_net_r", "passive_target_before_stop", "passive_net_r"}
        missing = action_required - set(ordered.columns)
        if missing:
            raise ValueError(f"training rows missing action labels: {sorted(missing)}")
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
        leakage_columns = {
            "event_start",
            "event_end",
            "target_before_stop",
            "net_r",
            "passive_filled",
            "market_target_before_stop",
            "market_net_r",
            "passive_target_before_stop",
            "passive_net_r",
            "market_budget_r",
            "passive_budget_r",
        }
        self.feature_names = [
            name
            for name in ordered.columns
            if name not in leakage_columns and pd.api.types.is_numeric_dtype(ordered[name])
        ]
        if not self.feature_names:
            raise ValueError("no numeric feature columns")
        x_base = base[self.feature_names].replace([np.inf, -np.inf], np.nan)
        x_calibration = calibration[self.feature_names].replace([np.inf, -np.inf], np.nan)
        self.win_model.fit(x_base, base["market_target_before_stop"].astype(int))
        self.r_model.fit(x_base, base["market_net_r"].astype(float))
        self.fill_model.fit(x_base, base["passive_filled"].astype(int))
        raw_calibration = self._positive_probability(self.win_model, x_calibration)
        self.calibrator.fit(raw_calibration, calibration["market_target_before_stop"].astype(int).to_numpy())
        raw_fill = self._positive_probability(self.fill_model, x_calibration)
        self.fill_calibrator.fit(raw_fill, calibration["passive_filled"].astype(int).to_numpy())
        self._fill_calibrator_fitted = True

        market_wins = base[
            base["market_target_before_stop"].astype(int).eq(1) & base["market_net_r"].notna()
        ]
        market_losses = base[
            base["market_target_before_stop"].astype(int).eq(0) & base["market_net_r"].notna()
        ]
        self._market_win_r_fitted, self._market_win_bounds = self._fit_return_head(
            self.market_win_r_model, market_wins, "market_net_r"
        )
        self._market_loss_r_fitted, self._market_loss_bounds = self._fit_return_head(
            self.market_loss_r_model, market_losses, "market_net_r"
        )

        passive_base = base[
            base["passive_filled"].astype(int).eq(1)
            & base["passive_target_before_stop"].notna()
            & base["passive_net_r"].notna()
        ]
        passive_calibration = calibration[
            calibration["passive_filled"].astype(int).eq(1)
            & calibration["passive_target_before_stop"].notna()
            & calibration["passive_net_r"].notna()
        ]
        minimum_passive = max(20, self.config.min_samples_leaf)
        if len(passive_base) >= minimum_passive and len(passive_calibration) >= 2:
            x_passive = passive_base[self.feature_names].replace([np.inf, -np.inf], np.nan)
            self.passive_win_model.fit(x_passive, passive_base["passive_target_before_stop"].astype(int))
            self.passive_r_model.fit(x_passive, passive_base["passive_net_r"].astype(float))
            raw_passive = self._positive_probability(
                self.passive_win_model,
                passive_calibration[self.feature_names].replace([np.inf, -np.inf], np.nan),
            )
            self.passive_calibrator.fit(
                raw_passive,
                passive_calibration["passive_target_before_stop"].astype(int).to_numpy(),
            )
            passive_wins = passive_base[passive_base["passive_target_before_stop"].astype(int).eq(1)]
            passive_losses = passive_base[passive_base["passive_target_before_stop"].astype(int).eq(0)]
            self._passive_win_r_fitted, self._passive_win_bounds = self._fit_return_head(
                self.passive_win_r_model, passive_wins, "passive_net_r"
            )
            self._passive_loss_r_fitted, self._passive_loss_bounds = self._fit_return_head(
                self.passive_loss_r_model, passive_losses, "passive_net_r"
            )
            self._passive_outcome_fitted = True
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

    @staticmethod
    def _expected_log(
        probability: float,
        risk_fraction: float,
        winner_net_r: float,
        loser_net_r: float,
        fixed_cost_fraction: float,
    ) -> float:
        win_return = risk_fraction * winner_net_r - fixed_cost_fraction
        loss_return = risk_fraction * loser_net_r - fixed_cost_fraction
        if win_return <= -1 or loss_return <= -1:
            return -np.inf
        return probability * log(1 + win_return) + (1 - probability) * log(1 + loss_return)

    @staticmethod
    def _conditional_return(
        model: HistGradientBoostingRegressor,
        vector: pd.DataFrame,
        fitted: bool,
        bounds: tuple[float, float],
        fallback: float,
        winner: bool,
    ) -> float:
        if not fitted:
            return float(fallback)
        prediction = float(model.predict(vector)[0])
        if not np.isfinite(prediction):
            return float(fallback)
        prediction = float(np.clip(prediction, bounds[0], bounds[1]))
        if winner and prediction <= 0:
            return float(fallback)
        if not winner and prediction >= 0:
            return float(fallback)
        return prediction

    def score(
        self,
        candidate: EventCandidate,
        risk_fraction: float,
        winner_net_r: float,
        loser_net_r: float,
        fixed_cost_fraction: float,
        passive_winner_net_r: float | None = None,
        passive_loser_net_r: float | None = None,
        passive_fixed_cost_fraction: float = 0.0,
    ) -> ScoredCandidate:
        if not self._fitted:
            raise RuntimeError("model not fitted")
        candidate_features = candidate_model_features(candidate)
        vector = pd.DataFrame(
            [{name: candidate_features.get(name, np.nan) for name in self.feature_names}]
        ).replace([np.inf, -np.inf], np.nan)
        raw_market_p = float(self._positive_probability(self.win_model, vector)[0])
        market_p = float(self.calibrator.predict([raw_market_p])[0])
        market_unconditional_r = float(self.r_model.predict(vector)[0])
        raw_fill = float(self._positive_probability(self.fill_model, vector)[0])
        fill = (
            float(self.fill_calibrator.predict([raw_fill])[0])
            if self._fill_calibrator_fitted
            else raw_fill
        )

        if self._passive_outcome_fitted:
            raw_passive_p = float(self._positive_probability(self.passive_win_model, vector)[0])
            passive_p = float(self.passive_calibrator.predict([raw_passive_p])[0])
            passive_unconditional_r = float(self.passive_r_model.predict(vector)[0])
        else:
            passive_p = market_p
            passive_unconditional_r = market_unconditional_r

        fallback_passive_winner = winner_net_r if passive_winner_net_r is None else passive_winner_net_r
        fallback_passive_loser = loser_net_r if passive_loser_net_r is None else passive_loser_net_r
        market_winner = self._conditional_return(
            self.market_win_r_model,
            vector,
            self._market_win_r_fitted,
            self._market_win_bounds,
            winner_net_r,
            True,
        )
        market_loser = self._conditional_return(
            self.market_loss_r_model,
            vector,
            self._market_loss_r_fitted,
            self._market_loss_bounds,
            loser_net_r,
            False,
        )
        passive_winner = self._conditional_return(
            self.passive_win_r_model,
            vector,
            self._passive_outcome_fitted and self._passive_win_r_fitted,
            self._passive_win_bounds,
            fallback_passive_winner,
            True,
        )
        passive_loser = self._conditional_return(
            self.passive_loss_r_model,
            vector,
            self._passive_outcome_fitted and self._passive_loss_r_fitted,
            self._passive_loss_bounds,
            fallback_passive_loser,
            False,
        )

        market_expected_r = market_p * market_winner + (1 - market_p) * market_loser
        passive_conditional_r = passive_p * passive_winner + (1 - passive_p) * passive_loser
        market_log = self._expected_log(
            market_p, risk_fraction, market_winner, market_loser, fixed_cost_fraction
        )
        passive_conditional_log = self._expected_log(
            passive_p,
            risk_fraction,
            passive_winner,
            passive_loser,
            passive_fixed_cost_fraction,
        )
        passive_log = fill * passive_conditional_log  # no fill => zero account return

        market_disagreement = abs(market_unconditional_r - market_expected_r)
        market_uncertainty = market_p * (1 - market_p)
        market_lower = market_log - self.config.lower_confidence_penalty * (
            market_uncertainty + market_disagreement
        ) * risk_fraction

        passive_disagreement = abs(passive_unconditional_r - passive_conditional_r)
        passive_uncertainty = fill * passive_p * (1 - passive_p) + fill * (1 - fill)
        passive_lower = passive_log - self.config.lower_confidence_penalty * (
            passive_uncertainty + fill * passive_disagreement
        ) * risk_fraction

        if passive_lower > market_lower:
            chosen_log = passive_log
            chosen_lower = passive_lower
            preferred = "PASSIVE_RETEST"
        else:
            chosen_log = market_log
            chosen_lower = market_lower
            preferred = "MARKETABLE"
        return ScoredCandidate(
            candidate=candidate,
            win_probability=market_p,
            expected_net_r=market_expected_r,
            passive_fill_probability=fill,
            expected_log_growth=chosen_log,
            lower_confidence_score=chosen_lower,
            passive_win_probability=passive_p,
            market_expected_log_growth=market_log,
            passive_expected_log_growth=passive_log,
            market_lower_confidence_score=market_lower,
            passive_lower_confidence_score=passive_lower,
            preferred_action=preferred,
            market_winner_net_r=market_winner,
            market_loser_net_r=market_loser,
            passive_winner_net_r=passive_winner,
            passive_loser_net_r=passive_loser,
            passive_conditional_expected_net_r=passive_conditional_r,
            market_unconditional_expected_net_r=market_unconditional_r,
            passive_unconditional_expected_net_r=passive_unconditional_r,
        )
